# TASK-US038-03 — LangGraph Node Span Instrumentation (`@otel_node_span` Decorator)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US038-03 |
| User Story | US-038 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the `@otel_node_span` decorator that wraps any async LangGraph node function in a child OTel span (AC-2). The decorator extracts span context from `AgentState["_otel_ctx"]`, starts a named child span under the root trace, and sets the four required span attributes: `intent_type`, `token_count`, `model_id`, `connector_id` (AC-4) — resolved from `AgentState` at call time. Apply the decorator to the five required pipeline nodes: Intent, Retrieval, Compression, Governance, and Routing.

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-sdk>=1.25`, `functools.wraps`

**File locations:**
- `src/observability/tracing/node_span.py` — `otel_node_span` decorator, `_set_node_attributes()`
- `src/agents/nodes/intent_node.py` — add decorator (extend only)
- `src/agents/nodes/retrieval_node.py` — add decorator (extend only)
- `src/agents/nodes/compression_node.py` — add decorator (extend only)
- `src/agents/nodes/governance_node.py` — add decorator (extend only)
- `src/agents/nodes/routing_node.py` — add decorator (extend only)

---

### `otel_node_span` decorator

```python
# src/observability/tracing/node_span.py
from __future__ import annotations
import functools
import logging
from typing import Callable, Awaitable, Any

from opentelemetry import trace, context as otel_context

from src.observability.tracing.root_span import RootSpanContext

logger  = logging.getLogger(__name__)
_TRACER = trace.get_tracer(__name__)


def otel_node_span(span_name: str | None = None):
    """
    Decorator factory for LangGraph async node functions.

    Usage:
        @otel_node_span()
        async def intent_node(state: AgentState) -> AgentState: ...

        @otel_node_span("retrieval.vector_search")
        async def retrieval_node(state: AgentState) -> AgentState: ...

    Behaviour:
    - Extracts RootSpanContext from state["_otel_ctx"].
    - Attaches the root span's context to the current async task.
    - Starts a child span named `span_name` (defaults to the function name).
    - Calls the wrapped node function inside the span.
    - Sets AC-4 attributes from state on the span after the call.
    - Records exception and re-raises on failure.
    """
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        name = span_name or fn.__name__

        @functools.wraps(fn)
        async def wrapper(state: dict, *args, **kwargs) -> Any:
            rsc: RootSpanContext | None = state.get("_otel_ctx")

            if rsc is None:
                # No root span in state — run without instrumentation (e.g. in unit tests)
                return await fn(state, *args, **kwargs)

            # Attach the root span context so the child span is correctly parented
            token = otel_context.attach(
                trace.set_span_in_context(rsc.span)
            )
            try:
                with _TRACER.start_as_current_span(
                    name,
                    kind = trace.SpanKind.INTERNAL,
                ) as span:
                    # Pre-call: set attributes available before node execution
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
                    # Post-call: set attributes populated by the node (e.g. model_id)
                    _set_post_attributes(span, result if isinstance(result, dict) else state)
                    return result
            finally:
                otel_context.detach(token)

        return wrapper
    return decorator


def _set_pre_attributes(span: trace.Span, state: dict) -> None:
    """
    AC-4: Set span attributes available at node entry time.
    These come from state fields set by upstream nodes.
    """
    _safe_set(span, "request_id",    str(state.get("request_id") or ""))
    _safe_set(span, "tenant_id",     str(state.get("tenant_id")  or ""))
    _safe_set(span, "intent_type",   str(state.get("intent")     or "unknown"))
    _safe_set(span, "model_id",      str(state.get("model_selected") or ""))

    # token_count: use compression-adjusted count if available, else pre-compression
    token_count = (
        state.get("compression_tokens_after")
        or state.get("compression_tokens_before")
        or _count_tokens_from_context(state)
    )
    _safe_set(span, "token_count", token_count)


def _set_post_attributes(span: trace.Span, result: dict) -> None:
    """
    AC-4: Set span attributes produced by the node (intent, model, tokens).
    Called with the returned state after node execution.
    """
    if result.get("intent"):
        span.set_attribute("intent_type", str(result["intent"]))
    if result.get("model_selected"):
        span.set_attribute("model_id",    str(result["model_selected"]))
    if result.get("compression_tokens_after") is not None:
        span.set_attribute("token_count", int(result["compression_tokens_after"]))
    if result.get("prompt_tokens") is not None:
        span.set_attribute("prompt_tokens",     int(result["prompt_tokens"]))
    if result.get("completion_tokens") is not None:
        span.set_attribute("completion_tokens", int(result["completion_tokens"]))


def _count_tokens_from_context(state: dict) -> int:
    """Estimate token count from ranked_context if explicit count not yet available."""
    chunks = state.get("ranked_context") or []
    return sum(len((c.get("text") or "").split()) for c in chunks)


def _safe_set(span: trace.Span, key: str, value) -> None:
    """Set span attribute; silently skip if value is empty/None."""
    if value is not None and value != "" and value != 0:
        span.set_attribute(key, value)
```

---

### Applying the decorator to the five required nodes

Each existing node file receives a single decorator line — no other changes:

```python
# src/agents/nodes/intent_node.py  (extend — do NOT rewrite)
from src.observability.tracing.node_span import otel_node_span

@otel_node_span("intent.classify")
async def intent_node(state: AgentState) -> AgentState:
    ...   # existing implementation unchanged
```

```python
# src/agents/nodes/retrieval_node.py  (extend — do NOT rewrite)
from src.observability.tracing.node_span import otel_node_span

@otel_node_span("retrieval.hybrid_search")
async def retrieval_node(state: AgentState) -> AgentState:
    ...
```

```python
# src/agents/nodes/compression_node.py  (extend — do NOT rewrite)
from src.observability.tracing.node_span import otel_node_span

@otel_node_span("compression.context_window")
async def compression_node(state: AgentState) -> AgentState:
    ...
```

```python
# src/agents/nodes/governance_node.py  (extend — do NOT rewrite)
from src.observability.tracing.node_span import otel_node_span

@otel_node_span("governance.pii_scan")
async def governance_node(state: AgentState) -> AgentState:
    ...
```

```python
# src/agents/nodes/routing_node.py  (extend — do NOT rewrite)
from src.observability.tracing.node_span import otel_node_span

@otel_node_span("routing.model_select")
async def routing_node(state: AgentState) -> AgentState:
    ...
```

## Acceptance Criteria

- [ ] A span named `"intent.classify"` appears as a child of the root span (AC-2)
- [ ] Spans for all five nodes — `intent.classify`, `retrieval.hybrid_search`, `compression.context_window`, `governance.pii_scan`, `routing.model_select` — are created per pipeline execution (AC-2)
- [ ] Each span has `intent_type` attribute set (non-empty after intent node runs) (AC-4)
- [ ] `model_id` attribute is set on the routing and later spans (AC-4)
- [ ] `token_count` attribute is set to the post-compression token count when available (AC-4)
- [ ] When `state["_otel_ctx"]` is `None` (unit test without OTel), the decorator calls the wrapped function without error (graceful no-op)
- [ ] Exception inside a node records the exception on the span and re-raises — the span status is `ERROR`

## Dependencies

- TASK-US038-01 (`setup_tracing()` — `TracerProvider` must be initialised before spans are created)
- TASK-US038-02 (`RootSpanContext`, `_otel_ctx` in `AgentState`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
