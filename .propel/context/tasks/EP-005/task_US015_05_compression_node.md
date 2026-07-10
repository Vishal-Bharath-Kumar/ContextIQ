# TASK-US015-05 — `compression_node` Implementation and Replay Trace Inclusion

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US015-05 |
| User Story | US-015 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `compression_node()` LangGraph node that calls `RuleBasedCompressor`, writes `compressed_context` and `removed_chunks` into `AgentState`, and ensures the removed chunk originals are captured in the Kafka `StateTransitionEvent` snapshot for EP-011 replay. This replaces the stub node referenced in TASK-US006-01. The node covers only US-015 (rule-based); semantic dedup (US-016) and LLM summarisation (US-017) will be added as sequential steps within this node in later tasks.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`

**File locations:**
- `src/agents/nodes/compression_node.py` — `compression_node()` implementation
- `src/agents/events/state_event_schema.py` — `StateTransitionEvent` extended with `removed_chunks_snapshot`
- `tests/agents/nodes/test_compression_node.py`

**`compression_node()` implementation:**

```python
# src/agents/nodes/compression_node.py
from src.compression.rule_based_compressor import RuleBasedCompressor
from src.agents.state                      import AgentState, ExecutionStatus

_compressor = RuleBasedCompressor()   # module-level singleton

async def compression_node(state: AgentState) -> dict:
    ranked_context = state.get("ranked_context") or []

    compressed, removed = _compressor.compress(ranked_context)

    return {
        "compressed_context": compressed,
        "removed_chunks":     removed,
        "ranked_context":     compressed,   # update ranked_context so routing_agent reads compressed list
        "current_node":       "compression_agent",
        "status":             ExecutionStatus.RUNNING,
    }
```

**`ranked_context` pass-through update:**
Setting `ranked_context = compressed` keeps the downstream `routing_agent` and `route_after_governance` predicate working without modification — they already read `ranked_context`. The original pre-compression content is available via `removed_chunks[*].original_content` for replay.

**Replay trace — `StateTransitionEvent` extension:**

Extend the Kafka event schema (TASK-US005-04 / TASK-US010-05 pattern) with a snapshot of removed chunks:

```python
# src/agents/events/state_event_schema.py  (extend — do NOT redefine)
class StateTransitionEvent(BaseModel):
    # --- existing fields (unchanged) ---
    event_id:                str
    request_id:              str
    user_id:                 str
    from_status:             str
    to_status:               str
    node_name:               str
    timestamp:               str
    duration_ms:             int
    error:                   str | None = None
    execution_plan_snapshot: dict | None = None   # US-010

    # --- US-015 addition ---
    removed_chunks_snapshot: list[dict] | None = None   # set by compression_agent only
```

**Populating the snapshot in the node wrapper:**

```python
# src/agents/graph.py  (extend wrap() — TASK-US005-04, TASK-US010-05 pattern)
plan    = merged.get("execution_plan")
removed = merged.get("removed_chunks")

await publisher.publish(StateTransitionEvent(
    # ... existing fields ...
    execution_plan_snapshot  = plan.model_dump()    if plan    is not None else None,
    removed_chunks_snapshot  = [r.model_dump() for r in removed] if removed is not None else None,
))
```

**Replay Service contract (EP-011):**
- `removed_chunks_snapshot` is set only on the `compression_agent` transition event
- Each dict in the list is a full `RemovedChunk.model_dump()` including `original_content`
- Replay Service can reconstruct the pre-compression context by merging `compressed_context` + deserialised `removed_chunks`

**Empty input guard:**
If `ranked_context` is empty or `None` (e.g. all chunks filtered in governance), `compression_node` returns `compressed_context = []` and `removed_chunks = []` without error — the pipeline proceeds to `routing_agent`.

## Acceptance Criteria

- [ ] `compression_node()` writes `compressed_context` as `list[RetrievedChunk]` to `AgentState`
- [ ] `compression_node()` writes `removed_chunks` as `list[RemovedChunk]` to `AgentState`
- [ ] `ranked_context` in `AgentState` is updated to the compressed list after the node runs
- [ ] `removed_chunks[*].original_content` is preserved (not `None`) for every removed chunk
- [ ] `StateTransitionEvent.removed_chunks_snapshot` is populated on the `compression_agent` Kafka event
- [ ] `StateTransitionEvent.removed_chunks_snapshot` is `None` for all other node transitions (backward-compatible)
- [ ] `compression_node()` handles empty `ranked_context` without raising an exception

## Dependencies

- TASK-US015-04 (`RuleBasedCompressor.compress()`)
- TASK-US015-01 (`RemovedChunk` — `removed_chunks` state field type)
- TASK-US005-04 (`StateTransitionEvent` — extended with `removed_chunks_snapshot`)
- TASK-US010-05 (`execution_plan_snapshot` pattern in `wrap()` — followed for `removed_chunks_snapshot`)
- TASK-US006-01 (`compression_agent` node stub — replaced by this implementation)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `compression_node` stub from TASK-US006-01 fully replaced — no `pass` or `return {}` remains
- [ ] `_compressor` is a module-level singleton — not re-instantiated per request
- [ ] `StateTransitionEvent` extension is backward-compatible (`removed_chunks_snapshot` defaults to `None`)
- [ ] Unit tests cover: normal compression, empty input, removed_chunks in state, Kafka snapshot payload shape
- [ ] `mypy --strict` passes; no `ruff` lint errors
