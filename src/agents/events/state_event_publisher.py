"""Kafka publisher for immutable agent state transition events.

``StateEventPublisher`` wraps an ``AIOKafkaProducer`` and publishes
``StateTransitionEvent`` records to ``contextiq.state.events``.  Publish
failures are logged at ERROR level but never propagate — observability must
not block pipeline execution.

``with_state_events`` is a node-wrapper factory that integrates the publisher
into a LangGraph node function, emitting entry / success / failure events
around every node invocation.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from src.agents.events.state_event_schema import StateTransitionEvent
from src.agents.state import AgentState, ExecutionStatus

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed_ms(t_start: float) -> int:
    return int((time.monotonic() - t_start) * 1000)


class StateEventPublisher:
    """Publishes ``StateTransitionEvent`` records to the Kafka state-events topic.

    The producer is injected at construction time so that tests can pass a
    mock without touching the real Kafka broker.

    Parameters
    ----------
    producer:
        A started ``AIOKafkaProducer`` instance.  Lifecycle management
        (``start`` / ``stop``) is the caller's responsibility.
    """

    TOPIC = "contextiq.state.events"

    def __init__(self, producer: object) -> None:
        self._producer = producer

    async def publish(self, event: StateTransitionEvent) -> None:
        """Send *event* to Kafka, swallowing any transport error.

        Publish failures are logged at ERROR level but never re-raised so that
        a Kafka outage never propagates into the agent pipeline.
        """
        try:
            await self._producer.send_and_wait(
                self.TOPIC,
                key=event.request_id.encode(),
                value=event.model_dump_json().encode(),
                headers=[("event_type", b"state.transition")],
            )
        except Exception:
            logger.error(
                "Failed to publish state transition event — "
                "request_id=%s event_id=%s node=%s",
                event.request_id,
                event.event_id,
                event.node_name,
                exc_info=True,
            )


def with_state_events(
    node_fn: Callable[[AgentState], object],
    node_name: str,
    publisher: StateEventPublisher,
    *,
    is_final: bool = False,
) -> Callable[[AgentState], object]:
    """Wrap a LangGraph node function with state-transition event publishing.

    Publishes three lifecycle events around *node_fn*:

    * **Entry** — ``state.status → RUNNING`` (duration_ms=0).
    * **Success** — ``RUNNING → COMPLETE`` when *is_final* is ``True``
      (routing_agent), otherwise ``RUNNING → RUNNING`` for intermediate nodes.
    * **Failure** — ``RUNNING → FAILED`` with the exception message when
      *node_fn* raises an unhandled exception.

    The exception is always re-raised so the graph's error handling is
    unaffected.

    Parameters
    ----------
    node_fn:   The original LangGraph node coroutine.
    node_name: Name of the node, stored in every emitted event.
    publisher: ``StateEventPublisher`` instance used to send events.
    is_final:  Set ``True`` for the terminal node (``routing_agent``) so a
               ``RUNNING → COMPLETE`` event is emitted on success.
    """

    async def _wrapper(state: AgentState) -> object:
        t_start = time.monotonic()
        from_status = str(state["status"])

        # Entry event: announce that this node is now running.
        await publisher.publish(
            StateTransitionEvent(
                event_id=str(uuid4()),
                request_id=state["request_id"],
                user_id=state["user_id"],
                from_status=from_status,
                to_status=ExecutionStatus.RUNNING,
                node_name=node_name,
                timestamp=_utcnow_iso(),
                duration_ms=0,
            )
        )

        try:
            result = await node_fn(state)
            # Success event: mark node complete (or whole pipeline complete).
            success_status = ExecutionStatus.COMPLETE if is_final else ExecutionStatus.RUNNING

            # Capture the execution_plan snapshot only for the intent_agent node.
            plan_snapshot: dict | None = None
            if node_name == "intent_agent" and isinstance(result, dict):
                merged = {**state, **result}
                plan = merged.get("execution_plan")
                if plan is not None:
                    plan_snapshot = plan.model_dump()

            removed_chunks_snapshot: list[dict] | None = None
            if node_name == "compression_agent" and isinstance(result, dict):
                removed_chunks = result.get("removed_chunks")
                if removed_chunks:
                    removed_chunks_snapshot = [
                        chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
                        for chunk in removed_chunks
                    ]

            await publisher.publish(
                StateTransitionEvent(
                    event_id=str(uuid4()),
                    request_id=state["request_id"],
                    user_id=state["user_id"],
                    from_status=ExecutionStatus.RUNNING,
                    to_status=success_status,
                    node_name=node_name,
                    timestamp=_utcnow_iso(),
                    duration_ms=_elapsed_ms(t_start),
                    execution_plan_snapshot=plan_snapshot,
                    removed_chunks_snapshot=removed_chunks_snapshot,
                )
            )
            return result
        except Exception as exc:
            # Failure event: include the exception message and failing node.
            await publisher.publish(
                StateTransitionEvent(
                    event_id=str(uuid4()),
                    request_id=state["request_id"],
                    user_id=state["user_id"],
                    from_status=ExecutionStatus.RUNNING,
                    to_status=ExecutionStatus.FAILED,
                    node_name=node_name,
                    timestamp=_utcnow_iso(),
                    duration_ms=_elapsed_ms(t_start),
                    error=str(exc),
                )
            )
            raise

    return _wrapper
