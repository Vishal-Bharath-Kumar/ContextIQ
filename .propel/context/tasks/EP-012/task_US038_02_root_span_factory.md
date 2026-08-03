# TASK-US038-02 — Root Span Factory for MCP Tool Calls and `request_id` → OTel Trace ID

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US038-02 |
| User Story | US-038 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `start_root_span()` — the factory function that creates the root OTel span for every inbound MCP tool call (AC-1) and seeds it with the `request_id` UUID mapped to an OTel-compatible 128-bit trace ID. The span context is stored in `AgentState` so all downstream pipeline node and connector child spans (TASK-US038-03/04) inherit the same trace ID. A `MCPTraceMiddleware` middleware alternative is also provided for FastMCP-based deployments.

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-sdk>=1.25`, `opentelemetry-api>=1.25`

**File locations:**
- `src/observability/tracing/root_span.py` — `start_root_span()`, `RootSpanContext`, `MCPTraceMiddleware`
- `src/agents/state.py` — extend `AgentState` with `_otel_ctx`
- `src/gateway/mcp_handler.py` — call `start_root_span()` before invoking the LangGraph pipeline

---

### `request_id` → OTel trace ID mapping

OTel trace IDs are 128-bit integers. A UUID is also 128 bits. The mapping is direct: strip the hyphens from the UUID hex string → 32 hex characters = 128 bits. This makes every Jaeger trace directly searchable by the `request_id` that appears in API responses and PostgreSQL audit records (AC-1, AC-6).

```
request_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
trace_id   = 0x3fa85f6457174562b3fc2c963f66afa6   (128-bit int)
```

---

### `start_root_span()`

```python
# src/observability/tracing/root_span.py
from __future__ import annotations
import uuid
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing      import Generator

from opentelemetry                          import trace, context as otel_context
from opentelemetry.sdk.trace                import ReadableSpan
from opentelemetry.trace                    import (
    NonRecordingSpan, SpanContext, TraceFlags, TraceState,
)

logger = logging.getLogger(__name__)

_TRACER = trace.get_tracer(__name__)


@dataclass(frozen=True)
class RootSpanContext:
    """
    Carries the active OTel span and its serialisable token for async propagation.
    Stored in AgentState['_otel_ctx'] so child spans can attach to this root.
    """
    span:        trace.Span
    token:       object   # opentelemetry context token returned by context.attach()
    trace_id_hex: str     # 32-char hex — equals request_id without hyphens (AC-1)


@contextmanager
def start_root_span(
    request_id: uuid.UUID,
    operation:  str = "mcp.tool_call",
) -> Generator[RootSpanContext, None, None]:
    """
    Context manager that:
    1. Derives a 128-bit OTel trace ID from request_id (AC-1).
    2. Creates a remote SpanContext with that trace ID (marks it as remote
       so OTel treats it as the root of a new trace, not a child of nothing).
    3. Starts a child span linked to that remote context.
    4. Attaches the span to the OTel context for the current async task.
    5. Yields a RootSpanContext for storage in AgentState.

    Usage:
        with start_root_span(request_id) as rsc:
            state["_otel_ctx"] = rsc
            await pipeline.invoke(state)
    """
    trace_id_int = _uuid_to_trace_id(request_id)
    trace_id_hex = f"{trace_id_int:032x}"

    # Build a synthetic remote SpanContext that carries our chosen trace ID.
    # span_id = first 8 bytes of the UUID (deterministic, not random).
    span_id_int = int(request_id.int >> 64) & 0xFFFFFFFFFFFFFFFF
    remote_ctx  = SpanContext(
        trace_id    = trace_id_int,
        span_id     = span_id_int,
        is_remote   = True,
        trace_flags = TraceFlags(TraceFlags.SAMPLED),
        trace_state = TraceState(),
    )
    parent_ctx = trace.set_span_in_context(NonRecordingSpan(remote_ctx))

    with _TRACER.start_as_current_span(
        operation,
        context    = parent_ctx,
        kind       = trace.SpanKind.SERVER,
    ) as span:
        span.set_attribute("request_id", str(request_id))
        span.set_attribute("otel.trace_id", trace_id_hex)

        token = otel_context.attach(otel_context.get_current())
        try:
            yield RootSpanContext(
                span         = span,
                token        = token,
                trace_id_hex = trace_id_hex,
            )
        finally:
            otel_context.detach(token)


def _uuid_to_trace_id(uid: uuid.UUID) -> int:
    """Map a UUID to a 128-bit OTel trace ID integer (strip hyphens, parse as hex)."""
    return int(uid.hex, 16)
```

---

### `MCPTraceMiddleware` (FastMCP deployment pattern)

For services using FastMCP, the middleware hooks into the tool-call lifecycle:

```python
# src/observability/tracing/root_span.py  (continued)
from fastmcp import Context as MCPContext   # type: ignore[import]


class MCPTraceMiddleware:
    """
    FastMCP middleware that wraps each tool call in a root OTel span (AC-1).
    Injects `_otel_ctx` into the MCP tool's context for downstream access.

    Registration:
        mcp = FastMCP("ContextIQ")
        mcp.add_middleware(MCPTraceMiddleware())
    """

    async def __call__(self, ctx: MCPContext, call_next):
        raw_id    = ctx.meta.get("request_id") if ctx.meta else None
        req_id    = uuid.UUID(raw_id) if raw_id else uuid.uuid4()

        with start_root_span(req_id, operation=f"mcp.{ctx.tool_name}") as rsc:
            ctx.state["_otel_ctx"]      = rsc
            ctx.state["request_id"]     = str(req_id)
            ctx.state["otel_trace_id"]  = rsc.trace_id_hex
            return await call_next(ctx)
```

---

### `AgentState` extensions

```python
# src/agents/state.py  (extend existing TypedDict)
    _otel_ctx:      object | None    # RootSpanContext — not serialised to JSON
    otel_trace_id:  str | None       # 32-char hex trace ID = request_id without hyphens
```

---

### MCP handler integration

```python
# src/gateway/mcp_handler.py  (extend existing tool call handler — do NOT rewrite)
from src.observability.tracing.root_span import start_root_span

async def handle_tool_call(request_id: uuid.UUID, tool_input: dict) -> dict:
    with start_root_span(request_id, operation="mcp.context_query") as rsc:
        state = build_initial_state(tool_input)
        state["_otel_ctx"]     = rsc
        state["otel_trace_id"] = rsc.trace_id_hex
        return await pipeline.invoke(state)
```

## Acceptance Criteria

- [ ] `_uuid_to_trace_id(uuid.UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6"))` equals `0x3fa85f6457174562b3fc2c963f66afa6` — verified in unit test (AC-1)
- [ ] Root span's `trace_id` in hex equals `request_id.hex` (no hyphens) — confirmed via `InMemorySpanExporter` (AC-1)
- [ ] Root span has attributes `request_id` and `otel.trace_id` set
- [ ] `AgentState["otel_trace_id"]` is populated after `start_root_span()` — available to `trace_writer_node` for cross-referencing
- [ ] `MCPTraceMiddleware` injects `_otel_ctx` into the MCP context state before calling `call_next`
- [ ] Detaching the OTel context token in the `finally` block ensures no context leak across concurrent requests

## Dependencies

- TASK-US038-01 (`setup_tracing()` must be called before root spans are created)
- US-005 (`request_id` generated before `start_root_span()` is called)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
