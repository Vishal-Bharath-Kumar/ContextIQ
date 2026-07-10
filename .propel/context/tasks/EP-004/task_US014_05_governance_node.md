# TASK-US014-05 — `governance_node` Implementation, Per-Intent Config, and `ranked_context` State Write

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US014-05 |
| User Story | US-014 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend / Config |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `governance_node()` LangGraph node that instantiates `ContextRanker` with the intent-appropriate `RankingWeights`, calls `rank()` on `AgentState.raw_context`, and writes the result to `AgentState.ranked_context`. This replaces the pass-through stub used in TASK-US007-01 and activates the `route_after_governance` token-budget decision (TASK-US006-01). Weights are overridable per intent type via environment-sourced admin settings.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`, `pydantic>=2.0`

**File locations:**
- `src/agents/nodes/governance_node.py` — `governance_node()` implementation
- `src/retrieval/ranking/settings.py` — `RankingSettings` Pydantic settings model
- `tests/agents/nodes/test_governance_node.py`

**`RankingSettings` — admin-configurable weight overrides:**

```python
# src/retrieval/ranking/settings.py
from pydantic_settings import BaseSettings
from src.retrieval.ranking.weights import RankingWeights, INTENT_WEIGHT_TABLE, DEFAULT_WEIGHTS
from src.agents.schemas.intent     import IntentType

class RankingSettings(BaseSettings):
    """Per-intent weight overrides loaded from environment at startup.

    Format: RANKING_WEIGHTS_<INTENT_TYPE_UPPER>=<v_weight>,<k_weight>,<r_weight>
    Example: RANKING_WEIGHTS_INCIDENT=0.2,0.6,0.2
    """
    relevance_threshold:        float = 0.5
    recency_half_life_days:     float = 30.0

    # Per-intent overrides (optional — fallback to INTENT_WEIGHT_TABLE)
    ranking_weights_debugging:    str | None = None
    ranking_weights_code_gen:     str | None = None
    ranking_weights_architecture: str | None = None
    ranking_weights_docs:         str | None = None
    ranking_weights_incident:     str | None = None
    ranking_weights_metrics:      str | None = None
    ranking_weights_code_review:  str | None = None
    ranking_weights_general:      str | None = None

    model_config = SettingsConfigDict(env_prefix="RANKING_", env_file=".env")

    def get_weights(self, intent_type: IntentType) -> RankingWeights:
        env_val = getattr(self, f"ranking_weights_{intent_type.replace('-', '_')}", None)
        if env_val:
            v, k, r = (float(x) for x in env_val.split(","))
            return RankingWeights(vector_weight=v, keyword_weight=k, recency_weight=r)
        return INTENT_WEIGHT_TABLE.get(intent_type, DEFAULT_WEIGHTS)
```

**`governance_node()` implementation:**

```python
# src/agents/nodes/governance_node.py
from src.retrieval.ranking.ranker   import ContextRanker
from src.retrieval.ranking.settings import RankingSettings
from src.agents.schemas.intent      import IntentType
from src.agents.state               import AgentState, ExecutionStatus

_ranking_settings = RankingSettings()   # loaded once at module import

async def governance_node(state: AgentState) -> dict:
    raw_context   = state.get("raw_context") or []
    intent_type   = IntentType(state["intent_type"])
    token_budget  = state["execution_plan"].token_budget_total

    weights = _ranking_settings.get_weights(intent_type)
    ranker  = ContextRanker(
        weights   = weights,
        threshold = _ranking_settings.relevance_threshold,
    )

    ranked = ranker.rank(raw_context, token_budget)

    return {
        "ranked_context": ranked,
        "current_node":   "governance_agent",
        "status":         ExecutionStatus.RUNNING,
    }
```

**Connection to `route_after_governance`:**

After `governance_node` writes `ranked_context`, the existing routing predicate (TASK-US006-01) counts its total tokens to decide compress vs. skip:

```python
# src/agents/routing.py  (TASK-US006-01 — no change needed)
def route_after_governance(state: AgentState) -> str:
    plan          = state.get("execution_plan") or {}
    budget        = plan.get("token_budget_total", 8000)
    ranked_tokens = sum(c.get("token_count", 0) for c in (state.get("ranked_context") or []))
    return "compress" if ranked_tokens > budget else "skip"
```

Note: `route_after_governance` currently uses `.get("token_count")` on dict objects. Since `ranked_context` is now `list[RetrievedChunk]`, update the predicate to use `count_tokens(c.content)`:

```python
# Update in src/agents/routing.py
from src.retrieval.ranking.filters import count_tokens

def route_after_governance(state: AgentState) -> str:
    plan          = state["execution_plan"]
    budget        = plan.token_budget_total
    ranked_tokens = sum(count_tokens(c.content) for c in (state.get("ranked_context") or []))
    return "compress" if ranked_tokens > budget else "skip"
```

## Acceptance Criteria

- [ ] `governance_node()` writes `ranked_context` as a `list[RetrievedChunk]` to `AgentState`
- [ ] All chunks in `ranked_context` have `score >= relevance_threshold`
- [ ] `ranked_context` is ordered descending by `score`
- [ ] Total token count of `ranked_context` does not exceed `execution_plan.token_budget_total`
- [ ] `RANKING_WEIGHTS_INCIDENT=0.2,0.6,0.2` environment variable is loaded and overrides the default incident weights
- [ ] `route_after_governance` correctly reads token count from `RetrievedChunk.content` (typed access, not dict `.get()`)
- [ ] `governance_node()` returns an empty `ranked_context` list (not `None`) when `raw_context` is empty

## Dependencies

- TASK-US014-04 (`ContextRanker.rank()`)
- TASK-US014-01 (`RankingWeights`, `INTENT_WEIGHT_TABLE`)
- TASK-US012-05 (`retrieval_agent` writes `raw_context` — prerequisite at runtime)
- TASK-US010-01 (`ExecutionPlan.token_budget_total` — typed access)
- TASK-US006-01 (`route_after_governance` predicate — minor update to typed chunk access)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `governance_node` pass-through stub from TASK-US007-01 is fully replaced — no `ranked_context = raw_context` assignments remain
- [ ] `_ranking_settings` is a module-level singleton — not re-initialised per node invocation
- [ ] Unit tests cover: normal ranking, empty raw_context, env-var weight override, threshold filtering
- [ ] `route_after_governance` uses `count_tokens(c.content)` — no `.get("token_count")` dict access
- [ ] `mypy --strict` passes; no `ruff` lint errors
