# TASK-US010-02 — Implement Token Budget Allocator (AIR-009)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US010-02 |
| User Story | US-010 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `allocate_token_budget()`, the function that distributes a total token budget across the selected knowledge sources using intent-aware weighting. The allocator is the runtime implementation of AIR-009 (token budget management). It is called by the plan generator (TASK-US010-03) and produces the `token_budget_per_source` field of `ExecutionPlan`.

## Implementation Details

**Technology:** Python 3.11+

**File locations:**
- `src/agents/planning/token_budget.py` — `allocate_token_budget()` and weight tables
- `tests/agents/planning/test_token_budget.py`

**Source-weight table (AIR-009 canonical weights):**

```python
# src/agents/planning/token_budget.py
from src.agents.schemas.intent import IntentType

# Relative weight per source for a given intent type.
# Sources not listed in a row receive weight 1 (equal share).
SOURCE_WEIGHT_TABLE: dict[IntentType, dict[str, int]] = {
    IntentType.DEBUGGING:    {"github": 3, "stackoverflow": 3, "jira": 2},
    IntentType.CODE_GEN:     {"github": 4, "confluence": 2},
    IntentType.ARCHITECTURE: {"confluence": 4, "github": 2, "miro": 2},
    IntentType.DOCS:         {"confluence": 4, "github": 2},
    IntentType.INCIDENT:     {"grafana": 4, "jira": 3, "pagerduty": 2},
    IntentType.METRICS:      {"grafana": 4, "datadog": 3},
    IntentType.CODE_REVIEW:  {"github": 1},
    IntentType.GENERAL:      {"confluence": 2, "github": 2, "stackoverflow": 2},
}

DEFAULT_TOTAL_BUDGET: int = 8_000
```

**`allocate_token_budget()` function:**

```python
def allocate_token_budget(
    intent_type: IntentType,
    source_list: list[str],
    total_budget: int = DEFAULT_TOTAL_BUDGET,
) -> dict[str, int]:
    """Distribute `total_budget` tokens across `source_list` using intent weights.

    Returns a mapping of source_id → token quota.
    Minimum allocation per source is 200 tokens to prevent starvation.
    """
    if not source_list:
        return {}

    weight_row  = SOURCE_WEIGHT_TABLE.get(intent_type, {})
    weights     = {src: weight_row.get(src, 1) for src in source_list}
    total_weight = sum(weights.values())

    MIN_ALLOC   = 200
    allocations: dict[str, int] = {}
    remainder   = total_budget

    # Proportional allocation with floor guarantee
    for src in source_list[:-1]:           # all but last
        raw   = int(total_budget * weights[src] / total_weight)
        quota = max(raw, MIN_ALLOC)
        allocations[src] = quota
        remainder -= quota

    # Last source absorbs rounding remainder
    allocations[source_list[-1]] = max(remainder, MIN_ALLOC)

    return allocations
```

**Edge cases:**
- `source_list` is empty → return `{}` (fallback handled upstream)
- Single source → receives `total_budget` minus floor rounding, minimum 200
- Total allocation may slightly exceed `total_budget` when the floor guarantee is applied for many low-weight sources; callers must tolerate this (delta < `len(source_list) * MIN_ALLOC`)

## Acceptance Criteria

- [ ] `allocate_token_budget(IntentType.INCIDENT, ["grafana", "jira", "pagerduty"], 8000)` returns three entries that sum to ≥ 8 000 (floor rounding may exceed)
- [ ] `grafana` receives the largest allocation for `IntentType.INCIDENT` (weight 4 vs 3 and 2)
- [ ] Every source in `source_list` receives at least 200 tokens
- [ ] `allocate_token_budget(IntentType.CODE_REVIEW, ["github"], 8000)` returns `{"github": 8000}`
- [ ] `allocate_token_budget(IntentType.GENERAL, [], 8000)` returns `{}`
- [ ] Unit tests cover: multi-source proportional split, single source, empty list, floor guarantee

## Dependencies

- TASK-US009-03 (`SOURCE_MAP` — `source_list` values are a subset of mapped keys)
- TASK-US010-01 (`ExecutionPlan.token_budget_per_source` field — receives output of this function)
- AIR-009 (token budget management specification)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for `src/agents/planning/token_budget.py`
- [ ] `SOURCE_WEIGHT_TABLE` covers all 8 intent types
- [ ] `mypy --strict` passes; no `ruff` lint errors
