# TASK-US009-02 — Extend AgentState with Intent Classification Fields

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US009-02 |
| User Story | US-009 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Extend the `AgentState` TypedDict (defined in TASK-US005-01) with the three fields required to carry intent classification results through the LangGraph pipeline: `intent_type`, `intent_confidence`, and `intent_source_list`. These fields are written by the Intent node and consumed by the Retrieval node and routing predicates.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`, `typing_extensions`

**File locations:**
- `src/agents/state.py` — `AgentState` TypedDict extension
- `tests/agents/test_state.py` — state schema validation tests

**State field additions:**

```python
# src/agents/state.py  (extend existing TypedDict — do NOT redefine it)
from typing import Optional
from src.agents.schemas.intent import IntentType

class AgentState(TypedDict, total=False):
    # --- existing fields (US-005) ---
    session_id:       str
    user_prompt:      str
    execution_trace:  list[dict]
    status:           ExecutionStatus
    error:            Optional[str]

    # --- US-009 additions ---
    intent_type:       Optional[IntentType]   # canonical intent label
    intent_confidence: Optional[float]        # classifier confidence, 0.0–1.0
    intent_source_list: Optional[list[str]]   # source keys derived in TASK-US009-03
```

**Validation rules:**
- `intent_confidence` must satisfy `0.0 ≤ value ≤ 1.0`; enforce with a `__post_init__`-style validator or `Annotated[float, Field(ge=0.0, le=1.0)]` on the Pydantic companion model used in tests
- `intent_source_list` is `None` until the source-selection mapper (TASK-US009-03) populates it; the Retrieval Agent must treat `None` as "query all sources"

**Routing predicate contract:**

The existing `route_after_intent` predicate in `src/agents/routing.py` (TASK-US006-01) already reads `state.get("intent_confidence")`. After this task the field is always present after `intent_node` runs, so the `or 1.0` fallback can be removed:

```python
# Before (defensive fallback):
if (state.get("intent_confidence") or 1.0) < 0.6:

# After (field is guaranteed):
if state["intent_confidence"] < 0.6:
```

## Acceptance Criteria

- [ ] `AgentState` TypedDict contains `intent_type`, `intent_confidence`, and `intent_source_list` fields
- [ ] `intent_node()` output dict merges cleanly into `AgentState` without `KeyError` or type mismatch
- [ ] `route_after_intent` reads `intent_confidence` without fallback and routing logic is unchanged
- [ ] Existing US-005 state tests continue to pass after the extension
- [ ] `mypy --strict` reports no new errors on `state.py`

## Dependencies

- TASK-US005-01 (`AgentState` TypedDict — must not be redefined, only extended)
- TASK-US009-01 (`intent_node()` writes `intent_type` and `intent_confidence`)
- TASK-US009-03 (`intent_source_list` populated by source-selection mapper)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `AgentState` is the single canonical state definition — no duplicate TypedDicts
- [ ] Unit tests assert field presence and type after a mocked `intent_node` run
- [ ] `mypy --strict` passes; no `ruff` lint errors
