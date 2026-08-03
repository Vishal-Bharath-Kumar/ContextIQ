# TASK-US009-04 — Low-Confidence Fallback and Clarification Routing

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US009-04 |
| User Story | US-009 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Harden the low-confidence fallback path for the Intent Agent. When `intent_confidence < 0.6` the pipeline must flag the result and route to the `clarification_response` node rather than proceeding to retrieval. This task updates `route_after_intent`, the `clarification_node`, and ensures the execution state carries a `requires_clarification` flag for downstream consumers and audit.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`

**File locations:**
- `src/agents/routing.py` — `route_after_intent` predicate update
- `src/agents/nodes/clarification_node.py` — clarification response construction
- `src/agents/state.py` — `requires_clarification` flag (add alongside US-009-02 fields)
- `tests/agents/test_routing.py`

**Updated `route_after_intent` predicate:**

```python
# src/agents/routing.py
def route_after_intent(state: AgentState) -> str:
    if state.get("status") == ExecutionStatus.FAILED:
        return "failed"
    confidence = state["intent_confidence"]          # guaranteed after TASK-US009-02
    if confidence < 0.6:
        return "clarification"
    return "retrieval"
```

**`requires_clarification` state flag:**

```python
# src/agents/state.py  (add to US-009 additions block)
requires_clarification: Optional[bool]   # True when confidence < 0.6
```

**`clarification_node` update — include flag and low-confidence message:**

```python
# src/agents/nodes/clarification_node.py
async def clarification_node(state: AgentState) -> dict:
    confidence = state["intent_confidence"]
    intent     = state.get("intent_type", "unknown")
    return {
        "requires_clarification": True,
        "status": ExecutionStatus.COMPLETE,
        "final_response": {
            "type":    "clarification",
            "message": (
                f"Your request was interpreted as '{intent}' with low confidence "
                f"({confidence:.0%}). Could you provide more detail so I can give "
                "you the most relevant answer?"
            ),
        },
    }
```

**Threshold constant:**

Define `INTENT_CONFIDENCE_THRESHOLD = 0.6` in `src/agents/config.py` and import it in both `routing.py` and `source_selector.py` to avoid magic numbers.

```python
# src/agents/config.py
INTENT_CONFIDENCE_THRESHOLD: float = 0.6   # US-009 AC-5
```

**Execution-state contract:**
- `requires_clarification = True` is written only when the clarification path is taken; it is `None` (absent) on the happy path
- The value is included in the execution trace (TASK-US005-04 publisher) so replays can distinguish clarification exits from successful completions

## Acceptance Criteria

- [ ] `route_after_intent` returns `"clarification"` for `intent_confidence = 0.59`
- [ ] `route_after_intent` returns `"retrieval"` for `intent_confidence = 0.60` (boundary)
- [ ] `route_after_intent` returns `"failed"` when `status == ExecutionStatus.FAILED` regardless of confidence
- [ ] `clarification_node` sets `requires_clarification = True` and `status = COMPLETE`
- [ ] `final_response.type` is `"clarification"` when the clarification path is taken
- [ ] `INTENT_CONFIDENCE_THRESHOLD` is the single source of truth — no inline `0.6` literals in routing or source-selector code
- [ ] Unit tests cover: boundary at 0.60, below-threshold at 0.59, FAILED override

## Dependencies

- TASK-US009-01 (`intent_node` produces `intent_confidence`)
- TASK-US009-02 (`AgentState` carries `requires_clarification`)
- TASK-US009-03 (`select_sources` imports `INTENT_CONFIDENCE_THRESHOLD`)
- TASK-US006-01 (`clarification_response` node registered in pipeline topology)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `INTENT_CONFIDENCE_THRESHOLD` defined once in `config.py` and imported everywhere it is used
- [ ] Unit tests cover all three routing outcomes with boundary-value inputs
- [ ] Integration test asserts end-to-end clarification response for a low-confidence prompt
- [ ] `mypy --strict` passes; no `ruff` lint errors
