# TASK-US010-05 — Execution Trace Persistence of Plan for Replay and Audit

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US010-05 |
| User Story | US-010 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Event-Driven / Observability |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Extend the `StateTransitionEvent` Kafka schema (TASK-US005-04) with an optional `execution_plan_snapshot` field so that the plan produced by the Intent Agent is captured in the immutable event stream. This allows the Replay Service (EP-011) to reconstruct the exact execution context for any historical request without re-running intent classification.

## Implementation Details

**Technology:** Python 3.11+, `aiokafka`, `pydantic>=2.0`

**File locations:**
- `src/agents/events/state_event_schema.py` — `StateTransitionEvent` extended
- `src/agents/graph.py` — node wrapper updated to include plan snapshot on intent node transition
- `tests/agents/events/test_state_event_schema.py`

**Extended `StateTransitionEvent` schema:**

```python
# src/agents/events/state_event_schema.py
class StateTransitionEvent(BaseModel):
    # --- existing fields (TASK-US005-04, unchanged) ---
    event_id:     str
    request_id:   str
    user_id:      str
    from_status:  str
    to_status:    str
    node_name:    str
    timestamp:    str
    duration_ms:  int
    error:        str | None = None

    # --- US-010 addition ---
    execution_plan_snapshot: dict | None = None   # serialised ExecutionPlan, set only by intent_agent
```

**Populating the snapshot in the node wrapper:**

The wrapper in `src/agents/graph.py` already publishes a `StateTransitionEvent` after each node completes. Extend `wrap()` to include the plan snapshot when the node name is `"intent_agent"`:

```python
# src/agents/graph.py  (extend TASK-US005-04 wrapper — do NOT replace)
def wrap(node_fn, node_name: str, publisher: StateEventPublisher):
    async def wrapper(state: AgentState) -> AgentState:
        t_start = time.monotonic()
        # ... existing pre-event publish ...
        result = await node_fn(state)

        # Merge result into working state for snapshot extraction
        merged = {**state, **result}
        plan   = merged.get("execution_plan")

        await publisher.publish(StateTransitionEvent(
            # ... existing fields ...
            node_name              = node_name,
            execution_plan_snapshot = plan.model_dump() if plan is not None else None,
        ))
        return result
    return wrapper
```

**Replay Service contract (EP-011):**
- The `execution_plan_snapshot` dict is stored verbatim by the Replay Service alongside the state transition record
- Replay can reconstruct `ExecutionPlan.model_validate(snapshot)` without re-invoking the LLM
- For all nodes other than `intent_agent` the field is `None` and the Replay Service ignores it

**Audit query pattern:**
- Events are keyed by `request_id` in Kafka partition; the Replay Service can pull all events for a request and locate the `intent_agent` transition to extract the plan
- `execution_plan_snapshot` is included in the Kafka message body (not headers) to keep it within the standard consumer deserialisation path

## Acceptance Criteria

- [ ] `StateTransitionEvent` schema accepts `execution_plan_snapshot` as `dict | None` with default `None`
- [ ] After `intent_node` completes, the published `StateTransitionEvent` contains a non-`None` `execution_plan_snapshot` with keys `sources`, `token_budget_total`, `token_budget_per_source`, `ranking_strategy`, `cache_eligible`
- [ ] All other node transitions (retrieval, governance, etc.) publish `execution_plan_snapshot = None`
- [ ] Existing `StateTransitionEvent` unit tests pass without modification (field is optional with default)
- [ ] `StateTransitionEvent.model_dump_json()` serialises `execution_plan_snapshot` correctly for Kafka payload

## Dependencies

- TASK-US005-04 (`StateTransitionEvent` schema and `StateEventPublisher` — extended, not replaced)
- TASK-US010-01 (`ExecutionPlan.model_dump()` — produces the snapshot dict)
- TASK-US010-03 (`intent_node()` returns `execution_plan` in state patch)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `execution_plan_snapshot` field addition is backward-compatible — existing consumers that ignore unknown fields are unaffected
- [ ] Unit test asserts `execution_plan_snapshot` is populated in the `intent_agent` post-transition event
- [ ] Integration test verifies the Replay Service (EP-011 stub) can deserialise and reconstruct `ExecutionPlan` from the snapshot
- [ ] `mypy --strict` passes; no `ruff` lint errors
