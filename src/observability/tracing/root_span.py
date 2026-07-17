"""Root span factory for MCP tool calls.

Creates a root OTel span whose trace ID is derived directly from the
``request_id`` UUID (AC-1).  All downstream pipeline nodes and connector
spans created in TASK-US038-03/04 attach to this root span by reading
``AgentState["_otel_ctx"]``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

logger = logging.getLogger(__name__)

_TRACER = trace.get_tracer(__name__)


@dataclass(frozen=True)
class RootSpanContext:
    """Carries the active OTel span and its serialisable token for async propagation.

    Stored in ``AgentState["_otel_ctx"]`` so child spans can attach to this root.
    """

    span: trace.Span
    token: object  # opentelemetry context token returned by context.attach()
    trace_id_hex: str  # 32-char hex — equals request_id without hyphens (AC-1)


@contextmanager
def start_root_span(
    request_id: uuid.UUID,
    operation: str = "mcp.tool_call",
) -> Generator[RootSpanContext, None, None]:
    """Context manager that creates the root OTel span for an MCP tool call.

    Steps:
    1. Derives a 128-bit OTel trace ID from *request_id* (AC-1).
    2. Creates a synthetic remote :class:`~opentelemetry.trace.SpanContext` so
       OTel treats the new span as the root of a fresh trace.
    3. Starts a child span linked to that remote context with
       ``SpanKind.SERVER``.
    4. Attaches the span to the OTel context for the current async task.
    5. Yields a :class:`RootSpanContext` for storage in ``AgentState``.

    The OTel context token is detached in the ``finally`` block to prevent
    context leaks across concurrent requests.

    Usage::

        with start_root_span(request_id) as rsc:
            state["_otel_ctx"]     = rsc
            state["otel_trace_id"] = rsc.trace_id_hex
            await pipeline.invoke(state)
    """
    trace_id_int = _uuid_to_trace_id(request_id)
    trace_id_hex = f"{trace_id_int:032x}"

    # span_id = first 8 bytes of the UUID — deterministic, not random.
    span_id_int = int(request_id.int >> 64) & 0xFFFFFFFFFFFFFFFF

    remote_ctx = SpanContext(
        trace_id=trace_id_int,
        span_id=span_id_int,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    parent_ctx = trace.set_span_in_context(NonRecordingSpan(remote_ctx))

    with _TRACER.start_as_current_span(
        operation,
        context=parent_ctx,
        kind=trace.SpanKind.SERVER,
    ) as span:
        span.set_attribute("request_id", str(request_id))
        span.set_attribute("otel.trace_id", trace_id_hex)

        token = otel_context.attach(otel_context.get_current())
        try:
            yield RootSpanContext(
                span=span,
                token=token,
                trace_id_hex=trace_id_hex,
            )
        finally:
            otel_context.detach(token)


def _uuid_to_trace_id(uid: uuid.UUID) -> int:
    """Map a UUID to a 128-bit OTel trace ID integer.

    Strips hyphens from the UUID hex string and parses it as a base-16 integer.
    The resulting value equals ``request_id.hex`` interpreted as a 128-bit int.
    """
    return int(uid.hex, 16)


# ---------------------------------------------------------------------------
# FastMCP middleware
# ---------------------------------------------------------------------------

try:
    from fastmcp import Context as MCPContext  # type: ignore[import-untyped]

    class MCPTraceMiddleware:
        """FastMCP middleware that wraps each tool call in a root OTel span (AC-1).

        Injects ``_otel_ctx`` into the MCP tool's context for downstream access.

        Registration::

            mcp = FastMCP("ContextIQ")
            mcp.add_middleware(MCPTraceMiddleware())
        """

        async def __call__(  # type: ignore[override]
            self,
            ctx: MCPContext,
            call_next: Callable[..., Coroutine[Any, Any, Any]],
        ) -> Any:  # noqa: ANN401 — return type depends on fastmcp call_next
            raw_id = ctx.meta.get("request_id") if ctx.meta else None
            req_id = uuid.UUID(raw_id) if raw_id else uuid.uuid4()

            with start_root_span(req_id, operation=f"mcp.{ctx.tool_name}") as rsc:
                ctx.state["_otel_ctx"] = rsc
                ctx.state["request_id"] = str(req_id)
                ctx.state["otel_trace_id"] = rsc.trace_id_hex
                return await call_next(ctx)

except ImportError:
    # fastmcp is optional; MCPTraceMiddleware is unavailable in environments
    # that do not install it (e.g., unit-test environments).
    pass
