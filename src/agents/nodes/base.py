"""NodeWrapper, @node_contract decorator, with_error_handling, and ContractViolationError.

This module enforces the LangGraph node contract:

* Every node receives the full ``AgentState``.
* A node may only update the fields declared in its ``NODE_OUTPUT_CONTRACTS``
  entry.  Attempting to write any other field raises ``ContractViolationError``
  **when** ``settings.debug`` is ``True`` (i.e. zero overhead in production).
* If a node forgets to set ``current_node``, the wrapper injects it
  automatically before returning.
* ``with_error_handling`` catches any unhandled exception, returns a
  structured ``{status: FAILED, error: ...}`` dict, and never re-raises.

Wrapper composition order (outermost last — execution order inner→outer):

    raw node fn
    └─ with_error_handling  (catches exceptions, returns failed state; innermost)
       └─ @node_contract    (field validation, DEBUG only)
          └─ with_node_logging  (TASK-US006-03, composed via ``NodeWrapper.wrap``)
             └─ with_state_events  (TASK-US005-04, outermost)

``NodeWrapper.wrap`` is the single entry-point used by graph assembly
(``graph.py``) to apply the full decoration stack.
"""
from __future__ import annotations

import functools
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, cast

from src.agents.config import settings
from src.agents.nodes.contracts import NODE_OUTPUT_CONTRACTS
from src.agents.state import AgentState, ExecutionStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# with_error_handling — innermost wrapper
# ---------------------------------------------------------------------------


def with_error_handling(
    node_fn: Callable[[AgentState], Awaitable[dict[str, Any]]],
    node_name: str,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Innermost node wrapper that converts any unhandled exception to a structured failed-state dict.

    The wrapper does **not** re-raise.  Instead it returns a partial state
    update that LangGraph merges into the current ``AgentState``.  Conditional
    edges in ``routing.py`` detect ``status == FAILED`` and route to
    ``pipeline_failed`` → END, so nodes after the failure are never executed.

    Args:
        node_fn:   The raw async node coroutine ``(AgentState) -> dict``.
        node_name: Used to populate ``failed_node`` in the error payload and
                   ``current_node`` in the returned state update.

    Returns:
        An async callable that never raises — all exceptions are converted to
        a ``{status, current_node, error}`` dict with a JSON-serialised error
        payload.
    """

    @functools.wraps(node_fn)
    async def wrapper(state: AgentState) -> dict[str, Any]:
        try:
            return await node_fn(state)
        except Exception as e:
            return {
                "status": ExecutionStatus.FAILED,
                "current_node": node_name,
                "error": json.dumps(
                    {
                        "failed_node": node_name,
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "timestamp": _utcnow_iso(),
                    }
                ),
            }

    return wrapper


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class ContractViolationError(RuntimeError):
    """Raised when a node writes a field outside its declared contract.

    Only raised when ``settings.debug`` is ``True`` so production pipelines
    incur zero enforcement overhead.
    """


# ---------------------------------------------------------------------------
# @node_contract decorator
# ---------------------------------------------------------------------------


def node_contract(node_name: str) -> Callable[[Callable[[AgentState], Awaitable[dict[str, Any]]]], Callable[[AgentState], Awaitable[dict[str, Any]]]]:
    """Decorator factory that validates a node's output fields at runtime.

    In non-debug mode the decorator is transparent — it returns the wrapped
    function with no additional call overhead beyond a single boolean check.

    Args:
        node_name: Must be a key in ``NODE_OUTPUT_CONTRACTS``.

    Returns:
        A decorator that wraps an ``async (AgentState) -> dict`` coroutine.

    Raises:
        KeyError: If *node_name* is not found in ``NODE_OUTPUT_CONTRACTS``.
        ContractViolationError: In debug mode, when the node returns a field
            outside its allowed set.
    """
    allowed: set[str] = NODE_OUTPUT_CONTRACTS[node_name]

    def decorator(fn: Callable[[AgentState], Awaitable[dict[str, Any]]]) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
        @functools.wraps(fn)
        async def wrapper(state: AgentState) -> dict[str, Any]:
            result: dict[str, Any] = await fn(state)

            # Inject current_node if the node forgot to set it.
            if "current_node" not in result:
                result["current_node"] = node_name

            if settings.debug:
                # status, current_node, and error are always permitted.
                universal = {"status", "current_node", "error"}
                unexpected = set(result.keys()) - allowed - universal
                if unexpected:
                    raise ContractViolationError(
                        f"Node '{node_name}' wrote unexpected fields: {unexpected}. "
                        f"Allowed: {allowed}"
                    )

            return result

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# NodeWrapper — composes the full decoration stack
# ---------------------------------------------------------------------------


class NodeWrapper:
    """Composes contract, logging, and event-publishing wrappers for a node.

    Usage::

        from src.agents.nodes.base import NodeWrapper

        wrapped = NodeWrapper.wrap(intent_node, "intent_agent", publisher=publisher)
        builder.add_node("intent_agent", wrapped)
    """

    @staticmethod
    def wrap(
        node_fn: Callable[[AgentState], Awaitable[dict[str, Any]]],
        node_name: str,
        publisher: object = None,
        *,
        is_final: bool = False,
    ) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
        """Apply the full wrapper stack to *node_fn*.

        Composition order (inner → outer):
          1. ``with_error_handling`` — exception→failed-state (innermost)
          2. ``@node_contract``      — field validation (DEBUG only)
          3. ``with_node_logging``   — structured node logging (TASK-US006-03)
          4. ``with_state_events``   — Kafka event publish (TASK-US005-04)

        ``with_node_logging`` and ``with_state_events`` are imported lazily so
        that tasks that implement them (US006-03, US005-04) are not hard
        dependencies at import time.  When a dependency is unavailable the
        relevant layer is silently skipped.

        Args:
            node_fn:   The raw async node coroutine.
            node_name: Name used for contract lookup, logging, and events.
            publisher: Optional ``StateEventPublisher``; omit in tests.
            is_final:  Passed through to ``with_state_events`` for the terminal
                       node (``routing_agent``).

        Returns:
            A fully decorated async callable suitable for ``builder.add_node``.
        """
        # Layer 1: error handling — catches any exception and returns a
        # structured failed-state dict so the pipeline never crashes the
        # LangGraph runtime (innermost; always applied).
        fn: Callable[..., Any] = with_error_handling(node_fn, node_name)

        # Layer 2: contract enforcement (always applied).
        # Use Any internally — intermediate wrappers may weaken the return
        # annotation; we cast back to the strict type at the return site.
        fn = node_contract(node_name)(fn)

        # Layer 2: structured logging (TASK-US006-03).
        try:
            from src.agents.nodes.logging import with_node_logging  # noqa: PLC0415

            fn = with_node_logging(fn, node_name)
        except ImportError:
            logger.debug("with_node_logging not yet available — skipping (TASK-US006-03)")

        # Layer 3: Kafka state-transition events (TASK-US005-04).
        if publisher is not None:
            from src.agents.events.state_event_publisher import StateEventPublisher, with_state_events

            if not isinstance(publisher, StateEventPublisher):
                raise TypeError(f"publisher must be StateEventPublisher, got {type(publisher).__name__}")
            fn = with_state_events(fn, node_name, publisher, is_final=is_final)

        return cast(Callable[[AgentState], Awaitable[dict[str, Any]]], fn)
