# TASK-US037-03 — LLM Cost Prometheus Metrics and `llm_metrics_node`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US037-03 |
| User Story | US-037 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define `contextiq_llm_cost_usd_total` and `contextiq_llm_tokens_total` Prometheus metrics that feed the Grafana "daily cost by model" and "token budget utilisation" panels (AC-3). Implement `llm_metrics_node()` — a LangGraph node positioned after the model response node — that assembles an `LLMCallRecord` from `AgentState`, writes to Langfuse via `LLMCostRecorder` (TASK-US037-01), and increments the Prometheus counters. The node is asynchronous and dispatches Langfuse writes as fire-and-forget tasks so it adds no latency.

## Implementation Details

**Technology:** Python 3.11+, `prometheus-client>=0.20`, LangGraph `>=0.2.0`, LiteLLM (`litellm.cost_per_token`)

**File locations:**
- `src/observability/cost/llm_metrics.py` — Prometheus metrics + `llm_metrics_node`
- `src/agents/graph.py` — register node (extend only)
- `tests/observability/test_llm_metrics_node.py`

---

### Prometheus metrics for LLM cost

```python
# src/observability/cost/llm_metrics.py
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from uuid     import UUID

from prometheus_client import Counter

from src.agents.state                  import AgentState
from src.observability.cost.schemas    import LLMCallRecord
from src.observability.cost.recorder   import LLMCostRecorder

logger = logging.getLogger(__name__)

_COST_LABEL_NAMES  = ["service", "model_id", "team_id", "tenant_id", "intent_type"]
_TOKEN_LABEL_NAMES = _COST_LABEL_NAMES + ["token_type"]  # token_type: "prompt"|"completion"

_SERVICE = "contextiq-api"

# AC-1 / AC-3: LLM cost counter — drives "daily cost by model" Grafana panel
contextiq_llm_cost_usd_total = Counter(
    "contextiq_llm_cost_usd_total",
    "Cumulative LLM spend in USD, labelled by model and team.",
    _COST_LABEL_NAMES,
)

# AC-1 / AC-3: Token counter — drives "token budget utilisation" Grafana panel
contextiq_llm_tokens_total = Counter(
    "contextiq_llm_tokens_total",
    "Cumulative LLM tokens consumed, split by prompt and completion.",
    _TOKEN_LABEL_NAMES,
)
```

---

### `llm_metrics_node()`

```python
async def llm_metrics_node(state: AgentState) -> AgentState:
    """
    LangGraph node — LLM Cost Metrics.

    Position: immediately after the model response node, before trace_writer_node.

    Steps:
    1. Build LLMCallRecord from AgentState (prompt_tokens, completion_tokens,
       model_selected, cost_usd computed via LiteLLM cost map).
    2. Increment Prometheus cost + token counters synchronously (AC-1, AC-3).
    3. Dispatch LLMCostRecorder.record_llm_call() as asyncio.create_task() (AC-4).
    """
    model_id: str        = state.get("model_selected") or "unknown"
    prompt_tokens: int   = state.get("prompt_tokens")     or 0
    completion_tokens: int = state.get("completion_tokens") or 0
    jwt_claims: dict     = state.get("jwt_claims") or {}
    user_id:    str      = jwt_claims.get("sub") or "anonymous"
    team_id:    str      = (
        state.get("team_id")
        or jwt_claims.get("team_id")
        or jwt_claims.get("groups", ["default"])[0]
    )
    tenant_id:  str      = state.get("tenant_id") or "default"
    intent:     str      = state.get("intent")    or "unknown"

    cost_usd = _compute_cost(model_id, prompt_tokens, completion_tokens)

    # Step 2: Prometheus increments (synchronous — no IO)
    cost_labels  = {
        "service":     _SERVICE,
        "model_id":    model_id,
        "team_id":     team_id,
        "tenant_id":   tenant_id,
        "intent_type": intent,
    }
    contextiq_llm_cost_usd_total.labels(**cost_labels).inc(cost_usd)
    contextiq_llm_tokens_total.labels(**cost_labels, token_type="prompt").inc(prompt_tokens)
    contextiq_llm_tokens_total.labels(**cost_labels, token_type="completion").inc(completion_tokens)

    # Step 3: Langfuse write — fire-and-forget (AC-4, no latency impact)
    record = LLMCallRecord(
        request_id        = _get_request_id(state),
        tenant_id         = tenant_id,
        model_id          = model_id,
        prompt_tokens     = prompt_tokens,
        completion_tokens = completion_tokens,
        cost_usd          = cost_usd,
        user_id           = user_id,
        team_id           = team_id,
        intent_type       = intent,
        timestamp         = datetime.now(tz=timezone.utc),
    )
    recorder: LLMCostRecorder = _get_recorder(state)
    if recorder:
        asyncio.create_task(
            _write_langfuse(recorder, record),
            name=f"llm_cost_{record.request_id}",
        )

    return {
        **state,
        "llm_cost_usd": cost_usd,   # expose in state for trace_writer_node
    }


async def _write_langfuse(recorder: LLMCostRecorder, record: LLMCallRecord) -> None:
    """Background coroutine — never raises."""
    try:
        recorder.record_llm_call(record)
    except Exception:
        logger.exception(
            "llm_metrics_node._write_langfuse failed request_id=%s", record.request_id
        )


def _compute_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Use LiteLLM's cost-per-token map to derive cost in USD.
    Falls back to 0.0 if the model is not in the cost map.
    """
    try:
        import litellm
        cost = litellm.completion_cost(
            model              = model_id,
            prompt_tokens      = prompt_tokens,
            completion_tokens  = completion_tokens,
        )
        return round(float(cost), 8)
    except Exception:
        logger.debug("litellm.completion_cost unavailable for model=%s", model_id)
        return 0.0


def _get_request_id(state: AgentState) -> UUID:
    import uuid
    raw = state.get("request_id")
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str):
        return uuid.UUID(raw)
    return uuid.uuid4()


# ------------------------------------------------------------------ #
# Injectable singleton                                                 #
# ------------------------------------------------------------------ #

_DEFAULT_RECORDER: LLMCostRecorder | None = None


def set_llm_cost_recorder(recorder: LLMCostRecorder) -> None:
    global _DEFAULT_RECORDER
    _DEFAULT_RECORDER = recorder


def _get_recorder(state: AgentState) -> LLMCostRecorder | None:
    config = state.get("_config") or {}
    return config.get("llm_cost_recorder") or _DEFAULT_RECORDER
```

---

### `StateGraph` registration

```python
# src/agents/graph.py — extend only; do NOT replace existing code
from src.observability.cost.llm_metrics import llm_metrics_node

# Position: after model_response node, before trace_writer_node
graph.add_node("llm_metrics",   llm_metrics_node)
graph.add_edge("model_response", "llm_metrics")
graph.add_edge("llm_metrics",   "trace_writer")
```

---

### `AgentState` extension

```python
# src/agents/state.py — extend existing TypedDict
    llm_cost_usd: float | None   # populated by llm_metrics_node
```

## Acceptance Criteria

- [ ] `contextiq_llm_cost_usd_total` increments by the computed `cost_usd` after each `llm_metrics_node` execution (AC-1)
- [ ] `contextiq_llm_tokens_total{token_type="prompt"}` increments by `prompt_tokens` (AC-1)
- [ ] `contextiq_llm_tokens_total{token_type="completion"}` increments by `completion_tokens` (AC-1)
- [ ] All five label dimensions are present: `service`, `model_id`, `team_id`, `tenant_id`, `intent_type` (AC-6 filter support)
- [ ] `_compute_cost()` returns `0.0` without raising when the model is not in LiteLLM's cost map
- [ ] `LLMCostRecorder.record_llm_call()` is called once per node execution via `asyncio.create_task()`
- [ ] `llm_cost_usd` is added to the returned `AgentState` for use by `trace_writer_node`

## Dependencies

- TASK-US037-01 (`LLMCallRecord`, `LLMCostRecorder`)
- US-019 model selection node (provides `model_selected`, `prompt_tokens`, `completion_tokens` in state)
- TASK-US034-04 (`trace_writer_node` — positioned immediately after this node)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
