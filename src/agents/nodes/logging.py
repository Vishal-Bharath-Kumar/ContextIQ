"""
with_node_logging — per-node structured logging, OTel child span, and Prometheus timing.

TASK-US006-03: Node Entry/Exit Structured Logging with Per-Node Timing.

Log events emitted
------------------
``node_entry``
    Fired immediately **before** the node coroutine executes.
    Fields: ``node``, ``request_id``, ``user_id``

``node_exit``
    Fired on successful completion.
    Fields: ``node``, ``request_id``, ``duration_ms``, ``output_fields``
    (``output_fields`` lists the keys present in the returned dict — never
    their values — so raw context and PII are never written to logs.)

``node_failed``
    Fired when the node raises any exception; the exception is re-raised
    after logging.
    Fields: ``node``, ``request_id``, ``duration_ms``, ``error``, ``exc_info``

OTel spans
----------
A child span ``pipeline.<node_name>`` is created under whatever span is
current at call-time (typically ``mcp.tools.call`` from the gateway layer).
Attributes set on the span: ``pipeline.node_name``, ``pipeline.request_id``,
``pipeline.duration_ms``, ``pipeline.status``.

Prometheus
----------
``contextiq_pipeline_node_duration_seconds`` histogram is observed with
labels ``node_name`` and ``status`` (``"success"`` or ``"failed"``).
"""
from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.agents.state import AgentState, ExecutionStatus
from src.agents.telemetry import node_duration_histogram


def with_node_logging(node_fn: Callable[[AgentState], Any], node_name: str) -> Callable[[AgentState], Any]:
    """Wrap *node_fn* with structured entry/exit logs, an OTel child span, and Prometheus timing.

    Args:
        node_fn:   The raw async node coroutine ``(AgentState) -> dict``.
        node_name: Human-readable node identifier used in log fields and span names.

    Returns:
        An async callable with the same signature as *node_fn*.
    """
    _logger = structlog.get_logger("contextiq.pipeline.node").bind(node=node_name)

    @functools.wraps(node_fn)
    async def wrapper(state: AgentState) -> dict[str, Any]:
        # Resolve the tracer lazily so the wrapper always uses the tracer
        # provider that is active at call time.  This is safe because
        # ``trace.get_tracer`` is O(1) and returns a stable proxy object.
        _tracer = trace.get_tracer("contextiq.agents")
        request_id = state["request_id"]
        bound = _logger.bind(request_id=request_id, user_id=state["user_id"])

        with _tracer.start_as_current_span(
            f"pipeline.{node_name}",
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            span.set_attribute("pipeline.node_name", node_name)
            span.set_attribute("pipeline.request_id", request_id)

            bound.info("node_entry", node=node_name)
            t_start = time.monotonic()

            try:
                result = await node_fn(state)
                duration = time.monotonic() - t_start

                # Detect failure returned by with_error_handling (no exception
                # propagated but the node signalled FAILED via a state dict).
                result_status = (
                    "failed"
                    if result.get("status") == ExecutionStatus.FAILED
                    else "success"
                )

                span.set_attribute("pipeline.duration_ms", int(duration * 1000))
                span.set_attribute("pipeline.status", result_status)
                if result_status == "failed":
                    span.set_status(StatusCode.ERROR, result.get("error") or "pipeline failed")

                node_duration_histogram.labels(
                    node_name=node_name, status=result_status
                ).observe(duration)

                bound.info(
                    "node_exit",
                    node=node_name,
                    duration_ms=round(duration * 1000, 1),
                    output_fields=list(result.keys()),
                )
                return result

            except Exception as e:
                duration = time.monotonic() - t_start
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
                node_duration_histogram.labels(
                    node_name=node_name, status="failed"
                ).observe(duration)
                bound.error(
                    "node_failed",
                    node=node_name,
                    duration_ms=round(duration * 1000, 1),
                    error=str(e),
                    exc_info=True,
                )
                raise

    return wrapper
