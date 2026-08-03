# TASK-US011-03 — `clarification_round` Counter and Recursive-Cap Guard

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US011-03 |
| User Story | US-011 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend |
| Priority | P1 |
| Points | 2 |
| Status | Draft |

## Description

Add a `clarification_round` integer counter to `AgentState` and update `route_after_intent` so that a second low-confidence classification never triggers another clarification loop. When `clarification_round >= 1` and confidence is still below threshold, the pipeline proceeds directly to retrieval using the fallback source list rather than issuing a second question. This enforces the US-011 AC-6 cap of exactly one clarification round-trip.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`

**File locations:**
- `src/agents/state.py` — `clarification_round` field added
- `src/agents/routing.py` — `route_after_intent` extended
- `src/agents/config.py` — `MAX_CLARIFICATION_ROUNDS` constant
- `tests/agents/test_routing.py`

**`AgentState` addition:**

```python
# src/agents/state.py  (add alongside existing US-009/US-010 fields)
clarification_round: int   # 0 on first pass; incremented to 1 before second-pass re-entry
```

**Config constant:**

```python
# src/agents/config.py
MAX_CLARIFICATION_ROUNDS: int = 1   # US-011 AC-6: cap at one round-trip
```

**Updated `route_after_intent` predicate:**

```python
# src/agents/routing.py
from src.agents.config import INTENT_CONFIDENCE_THRESHOLD, MAX_CLARIFICATION_ROUNDS

def route_after_intent(state: AgentState) -> str:
    if state.get("status") == ExecutionStatus.FAILED:
        return "failed"

    confidence          = state["intent_confidence"]
    clarification_round = state.get("clarification_round", 0)

    if confidence < INTENT_CONFIDENCE_THRESHOLD:
        if clarification_round >= MAX_CLARIFICATION_ROUNDS:
            # Cap reached: forced-retrieval with fallback sources (set by select_sources)
            return "retrieval"
        return "clarification"

    return "retrieval"
```

**`clarification_round` initialisation:**

The field defaults to `0` and must be set at pipeline initialisation in the `/v1/execute` endpoint:

```python
# src/agents/worker/execute.py  (AgentState construction at request entry)
initial_state: AgentState = {
    # ... existing fields ...
    "clarification_round": 0,
}
```

**Forced-retrieval branch when cap is reached:**

When `clarification_round >= 1` and confidence is still low:
- `select_sources()` already returns `FALLBACK_SOURCES` for confidence < 0.6 (TASK-US009-03)
- No additional source-list override is needed; the routing predicate simply returns `"retrieval"` and the existing fallback mechanism applies
- An OTel span attribute `intent.cap_forced_retrieval = True` is set in `intent_node` when this branch is taken

```python
# src/agents/nodes/intent_node.py  (extend OTel block — TASK-US009-05)
cap_forced = (
    result.confidence < INTENT_CONFIDENCE_THRESHOLD
    and state.get("clarification_round", 0) >= MAX_CLARIFICATION_ROUNDS
)
span.set_attribute("intent.cap_forced_retrieval", cap_forced)
```

## Acceptance Criteria

- [ ] `AgentState` contains `clarification_round: int` with value `0` at pipeline initialisation
- [ ] `route_after_intent` returns `"clarification"` when `confidence < 0.6` and `clarification_round == 0`
- [ ] `route_after_intent` returns `"retrieval"` when `confidence < 0.6` and `clarification_round == 1`
- [ ] `route_after_intent` returns `"retrieval"` when `confidence >= 0.6` regardless of `clarification_round`
- [ ] `MAX_CLARIFICATION_ROUNDS = 1` is the single source of truth — no inline `1` literals in routing code
- [ ] `intent.cap_forced_retrieval` OTel span attribute is `True` only when cap path is taken

## Dependencies

- TASK-US009-04 (`route_after_intent` predicate — extended here, not replaced)
- TASK-US009-05 (OTel span in `intent_node` — `intent.cap_forced_retrieval` attribute added)
- TASK-US011-04 (`clarification_reply` re-submission — increments `clarification_round` to `1` before re-entry)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit tests cover all four routing combinations: {low/high confidence} × {round 0/round 1}
- [ ] `MAX_CLARIFICATION_ROUNDS` defined once in `config.py` and imported wherever used
- [ ] `mypy --strict` passes; no `ruff` lint errors
