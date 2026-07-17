"""LangGraph node span decorator — TASK-US038-03.

Wraps any async LangGraph node function in a child OTel span parented to the
root span stored in ``AgentState["_otel_ctx"]`` (AC-2).  Sets the four
required span attributes (intent_type, token_count, model_id, connector_id)
from ``AgentState`` before and after the node executes (AC-4).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace

from src.observability.tracing.root_span import RootSpanContext

logger = logging.getLogger(__name__)
_TRACER = trace.get_tracer(__name__)


def otel_node_span(span_name: str | None = None) -> Callable:
    """Decorator factory for LangGraph async node functions.

    Usage::

        @otel_node_span()
        async def intent_node(state: AgentState) -> AgentState: ...

        @otel_node_span("retrieval.vector_search")
        async def retrieval_node(state: AgentState) -> AgentState: ...

    Behaviour:

    - Extracts :class:`~src.observability.tracing.root_span.RootSpanContext`
      from ``state["_otel_ctx"]``.
    - Attaches the root span's context to the current async task.
    - Starts a child span named *span_name* (defaults to the function name).
    - Calls the wrapped node function inside the span.
    - Sets AC-4 attributes from state on the span before and after the call.
    - Records exception and re-raises on failure; sets span status to ERROR.
    - When ``state["_otel_ctx"]`` is ``None`` the decorator is a transparent
      pass-through (safe in unit tests that run without OTel).
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        name = span_name or fn.__name__

        @functools.wraps(fn)
        async def wrapper(state: dict, *args: object, **kwargs: object) -> object:
            rsc: RootSpanContext | None = state.get("_otel_ctx")

            if rsc is None:
                # No root span in state — run without instrumentation (unit tests)
                return await fn(state, *args, **kwargs)

            # Attach the root span context so the child span is correctly parented
            token = otel_context.attach(trace.set_span_in_context(rsc.span))
            try:
                with _TRACER.start_as_current_span(
                    name,
                    kind=trace.SpanKind.INTERNAL,
                ) as span:
                    _set_pre_attributes(span, state)
                    try:
                        result = await fn(state, *args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(
                            trace.StatusCode.ERROR,
                            description=str(exc),
                        )
                        raise
                    _set_post_attributes(
                        span, result if isinstance(result, dict) else state
                    )
                    return result
            finally:
                otel_context.detach(token)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------


def _set_pre_attributes(span: trace.Span, state: dict) -> None:
    """Set span attributes available at node entry time (AC-4)."""
    _safe_set(span, "request_id",  str(state.get("request_id") or ""))
    _safe_set(span, "tenant_id",   str(state.get("tenant_id")  or ""))
    _safe_set(span, "intent_type", str(state.get("intent_type") or "unknown"))
    _safe_set(span, "model_id",    str(state.get("model_selected") or ""))

    # connector_id: populated by retrieval node; empty string otherwise
    _safe_set(span, "connector_id", str(state.get("connector_id") or ""))

    # token_count: prefer post-compression count, fall back to pre-compression
    # or rough estimate from ranked_context chunks
    token_count = (
        state.get("compression_tokens_after")
        or state.get("compression_tokens_before")
        or _count_tokens_from_context(state)
    )
    _safe_set(span, "token_count", token_count)


def _set_post_attributes(span: trace.Span, result: dict) -> None:
    """Set span attributes produced by the node (AC-4)."""
    if result.get("intent_type"):
        span.set_attribute("intent_type", str(result["intent_type"]))
    if result.get("model_selected"):
        span.set_attribute("model_id", str(result["model_selected"]))
    if result.get("compression_tokens_after") is not None:
        span.set_attribute("token_count", int(result["compression_tokens_after"]))
    if result.get("prompt_tokens") is not None:
        span.set_attribute("prompt_tokens", int(result["prompt_tokens"]))
    if result.get("completion_tokens") is not None:
        span.set_attribute("completion_tokens", int(result["completion_tokens"]))


def _count_tokens_from_context(state: dict) -> int:
    """Estimate token count from ranked_context when no explicit count is set."""
    chunks = state.get("ranked_context") or []
    return sum(len((c.get("text") or "").split()) for c in chunks)


def _safe_set(span: trace.Span, key: str, value: object) -> None:
    """Set a span attribute; skip silently when the value is empty / zero."""
    if value is not None and value != "" and value != 0:
        span.set_attribute(key, value)
