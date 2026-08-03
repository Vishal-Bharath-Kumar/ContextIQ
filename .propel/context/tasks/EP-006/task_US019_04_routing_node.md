# TASK-US019-04 — `routing_node()` LangGraph Node, OTel Spans, and Langfuse Trace

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US019-04 |
| User Story | US-019 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `routing_node()` — the LangGraph node that reads `intent_type` from `AgentState.execution_plan`, calls `ModelRouter.select()`, and writes `selected_model_id` and `routing_score` back to state. The node emits an OTel span and a Langfuse event capturing the routing decision (model ID + reasoning).

## Implementation Details

**Technology:** Python 3.11+, LangGraph, OpenTelemetry, Langfuse

**File locations:**
- `src/agents/nodes/routing_node.py` — `routing_node()` implementation
- `tests/agents/nodes/test_routing_node.py` — unit tests

**`routing_node()`:**

```python
# src/agents/nodes/routing_node.py
import time
from opentelemetry import trace
from langfuse import Langfuse
from langfuse.callback import CallbackHandler

from src.agents.state                       import AgentState
from src.model_router.router                import ModelRouter
from src.model_router.schemas.routing_weights import INTENT_ROUTING_WEIGHT_TABLE
from src.model_registry.cache.model_cache   import ModelListCache
from src.model_router.cache.scored_model_cache import ScoredModelCache
from src.model_router.config                import RoutingSettings

_tracer   = trace.get_tracer(__name__)
_settings = RoutingSettings()

# Module-level singletons — initialised once, not per-request
_FALLBACK_MODEL_ID = _settings.fallback_model_id   # "gpt-4o-mini"


async def routing_node(
    state:            AgentState,
    model_list_cache: ModelListCache,       # injected via functools.partial at graph build
    scored_cache:     ScoredModelCache,     # injected via functools.partial at graph build
    langfuse:         Langfuse | None,      # None when Langfuse disabled in env
) -> AgentState:
    with _tracer.start_as_current_span("model_router.select") as span:
        t0          = time.perf_counter()
        intent_type = (state.get("execution_plan") or {}).get("intent_type", "general")

        router = ModelRouter(
            model_list_cache   = model_list_cache,
            scored_model_cache = scored_cache,
        )

        selection = await router.select(intent_type=intent_type)

        if selection is None:
            selected_model_id = _FALLBACK_MODEL_ID
            routing_score     = 0.0
            routing_reason    = f"No eligible model found; defaulted to {_FALLBACK_MODEL_ID}"
        else:
            selected_model_id = selection.model_id
            routing_score     = selection.composite_score
            routing_reason    = (
                f"Selected '{selection.model_id}' for intent '{intent_type}' "
                f"(composite_score={selection.composite_score:.4f}, "
                f"quality={selection.quality_score:.2f}, "
                f"normalised_cost={selection.normalised_cost:.4f})"
            )

        latency_ms = (time.perf_counter() - t0) * 1000

        # OTel attributes
        span.set_attribute("routing.model_id",    selected_model_id)
        span.set_attribute("routing.score",       routing_score)
        span.set_attribute("routing.intent",      intent_type)
        span.set_attribute("routing.latency_ms",  round(latency_ms, 2))
        span.set_attribute("routing.fallback",    selection is None)

        # Langfuse event
        if langfuse is not None:
            langfuse.event(
                name      = "model_routing_decision",
                input     = {"intent_type": intent_type},
                output    = {"model_id": selected_model_id, "score": routing_score},
                metadata  = {
                    "routing_reason": routing_reason,
                    "latency_ms":     latency_ms,
                    "used_fallback":  selection is None,
                },
                session_id = state.get("session_id"),
            )

    return {
        **state,
        "selected_model_id": selected_model_id,
        "routing_score":     routing_score,
    }
```

**Langfuse instantiation:**

`langfuse` is injected at graph build time via `functools.partial`, following the per-request `make_langfuse_handler()` pattern from TASK-US017-05. When `langfuse_enabled=False` in `RoutingSettings`, the graph is wired with `langfuse=None` and the `if langfuse is not None` guard skips the event emission without branching the graph.

**Graph wiring (`src/agents/graph.py` — extend existing, do NOT replace):**

```python
import functools
from src.agents.nodes.routing_node import routing_node

builder.add_node(
    "routing",
    functools.partial(
        routing_node,
        model_list_cache = app_state.model_list_cache,   # from FastAPI app.state
        scored_cache     = app_state.scored_model_cache,
        langfuse         = make_langfuse_handler(request_id, user_id, session_id)
                           if settings.langfuse_enabled else None,
    ),
)
builder.add_edge("intent", "routing")
builder.add_edge("routing", "retrieval")
```

**`RoutingSettings` extension:**

```python
# src/model_router/config.py  — extend existing RoutingSettings
fallback_model_id: str = "gpt-4o-mini"
langfuse_enabled:  bool = True
```

## Acceptance Criteria

- [ ] `routing_node()` writes `selected_model_id` and `routing_score` to `AgentState`
- [ ] When `ModelRouter.select()` returns `None`, fallback model ID from `RoutingSettings.fallback_model_id` is used
- [ ] OTel span `model_router.select` is emitted with all 5 attributes (`model_id`, `score`, `intent`, `latency_ms`, `fallback`)
- [ ] Langfuse event `model_routing_decision` is emitted when `langfuse` is not `None`
- [ ] When `langfuse=None`, no exception is raised and no Langfuse code is executed
- [ ] Routing latency (`routing.latency_ms`) is < 50 ms in CI benchmark (mocked Redis)

## Dependencies

- TASK-US019-01 (`AgentState` extensions: `selected_model_id`, `routing_score`)
- TASK-US019-02 (`ScoredModelCache`, `ModelScore`)
- TASK-US019-03 (`ModelRouter.select()`)
- TASK-US017-05 (`make_langfuse_handler()` per-request pattern)
- US-010 (`AgentState.execution_plan.intent_type` — upstream node output)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests: successful selection, fallback on `None`, OTel span attribute assertions, Langfuse emission, `langfuse=None` guard
- [ ] CI benchmark: routing latency < 50 ms (measured via `pytest-benchmark`)
- [ ] `mypy --strict` passes; no `ruff` lint errors
