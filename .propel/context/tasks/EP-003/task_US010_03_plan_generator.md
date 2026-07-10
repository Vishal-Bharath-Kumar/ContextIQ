# TASK-US010-03 — Implement Execution Plan Generator and Intent Node Integration (AIR-007)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US010-03 |
| User Story | US-010 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend / AI |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement `generate_execution_plan()`, the pure function that assembles a complete `ExecutionPlan` from the classified intent result. Integrate it as the final step of `intent_node()` so the plan is written into `AgentState` in the same node invocation as classification. Plan generation must complete within 200 ms (the entire `intent_node` budget is 500 ms; classification uses ≈ 250 ms, leaving ≥ 250 ms for planning). This is the runtime implementation of AIR-007 (context planning logic).

## Implementation Details

**Technology:** Python 3.11+

**File locations:**
- `src/agents/planning/plan_generator.py` — `generate_execution_plan()` and helper tables
- `src/agents/nodes/intent_node.py` — extended to call plan generator and return `execution_plan`
- `tests/agents/planning/test_plan_generator.py`

**Ranking strategy selection table:**

```python
# src/agents/planning/plan_generator.py
from src.agents.schemas.intent import IntentType
from src.agents.schemas.execution_plan import RankingStrategy

RANKING_STRATEGY_MAP: dict[IntentType, RankingStrategy] = {
    IntentType.DEBUGGING:    RankingStrategy.HYBRID,
    IntentType.CODE_GEN:     RankingStrategy.SEMANTIC,
    IntentType.ARCHITECTURE: RankingStrategy.SEMANTIC,
    IntentType.DOCS:         RankingStrategy.SEMANTIC,
    IntentType.INCIDENT:     RankingStrategy.BM25,
    IntentType.METRICS:      RankingStrategy.BM25,
    IntentType.CODE_REVIEW:  RankingStrategy.HYBRID,
    IntentType.GENERAL:      RankingStrategy.HYBRID,
}

# Cache-eligible intent types: results are stable and unlikely to change
# between requests with identical prompts within a TTL window
CACHE_ELIGIBLE_INTENTS: frozenset[IntentType] = frozenset({
    IntentType.DOCS,
    IntentType.ARCHITECTURE,
    IntentType.CODE_GEN,
})
```

**`generate_execution_plan()` function:**

```python
from src.agents.schemas.execution_plan import ExecutionPlan
from src.agents.planning.token_budget import allocate_token_budget, DEFAULT_TOTAL_BUDGET
from src.agents.config import INTENT_CONFIDENCE_THRESHOLD

def generate_execution_plan(
    intent_type:   IntentType,
    confidence:    float,
    source_list:   list[str],
    total_budget:  int = DEFAULT_TOTAL_BUDGET,
) -> ExecutionPlan:
    """Assemble a fully-specified ExecutionPlan from the intent classification result.

    Called synchronously at the end of intent_node() — no I/O, must complete < 200 ms.
    """
    return ExecutionPlan(
        sources               = source_list,
        token_budget_total    = total_budget,
        token_budget_per_source = allocate_token_budget(intent_type, source_list, total_budget),
        ranking_strategy      = RANKING_STRATEGY_MAP[intent_type],
        cache_eligible        = intent_type in CACHE_ELIGIBLE_INTENTS,
    )
```

**Integration into `intent_node()` — full updated return value:**

```python
# src/agents/nodes/intent_node.py  (extends TASK-US009-01, TASK-US009-03, TASK-US009-05)
from src.agents.planning.plan_generator import generate_execution_plan

async def intent_node(state: AgentState) -> dict:
    with _tracer.start_as_current_span("intent_agent.classify") as span:
        t0     = time.perf_counter()
        raw    = await _chain.ainvoke({"prompt_text": state["user_prompt"]})
        result = IntentResult.model_validate(raw)
        sources = select_sources(result.intent_type, result.confidence)
        plan    = generate_execution_plan(result.intent_type, result.confidence, sources)
        latency_ms = (time.perf_counter() - t0) * 1000

        span.set_attributes({
            "intent.type":              result.intent_type,
            "intent.confidence":        result.confidence,
            "intent.latency_ms":        round(latency_ms, 2),
            "intent.low_confidence":    result.confidence < INTENT_CONFIDENCE_THRESHOLD,
            "intent.plan.sources":      ",".join(plan.sources),
            "intent.plan.strategy":     plan.ranking_strategy,
            "intent.plan.cache":        plan.cache_eligible,
        })

        return {
            "intent_type":        result.intent_type,
            "intent_confidence":  result.confidence,
            "intent_source_list": sources,
            "execution_plan":     plan,
        }
```

**Performance constraint:**
- `generate_execution_plan()` is pure (no I/O, no LLM calls) and performs only dict lookups and integer arithmetic → p99 latency < 1 ms in production
- The 200 ms plan-generation budget specified in US-010 AC-4 is trivially satisfied; the constraint effectively means the full intent node (classification + planning) must stay ≤ 500 ms (US-009 AC-3)

## Acceptance Criteria

- [ ] `generate_execution_plan(IntentType.INCIDENT, 0.9, ["grafana", "jira", "pagerduty"])` returns an `ExecutionPlan` with `ranking_strategy = "bm25"` and `cache_eligible = False`
- [ ] `generate_execution_plan(IntentType.DOCS, 0.85, ["confluence", "github"])` returns `cache_eligible = True` and `ranking_strategy = "semantic"`
- [ ] All 8 intent types are covered in `RANKING_STRATEGY_MAP` (KeyError raises immediately in tests)
- [ ] `intent_node()` return dict includes `execution_plan` as an `ExecutionPlan` instance
- [ ] `generate_execution_plan()` completes in < 1 ms for all 8 intent types (benchmark asserts this)
- [ ] `plan.token_budget_per_source` keys match `plan.sources` exactly (no orphan keys)

## Dependencies

- TASK-US010-01 (`ExecutionPlan` schema and `RankingStrategy` enum)
- TASK-US010-02 (`allocate_token_budget()`)
- TASK-US009-03 (`select_sources()` — produces `source_list` input)
- TASK-US009-04 (`INTENT_CONFIDENCE_THRESHOLD` constant from `config.py`)
- AIR-007 (context planning logic specification)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `generate_execution_plan()` is the single plan construction site — no inline plan-building in node files
- [ ] Unit tests cover all 8 intent types for both `ranking_strategy` and `cache_eligible` values
- [ ] Benchmark test asserts `generate_execution_plan()` runs in < 1 ms (mocked dependencies)
- [ ] `mypy --strict` passes; no `ruff` lint errors
