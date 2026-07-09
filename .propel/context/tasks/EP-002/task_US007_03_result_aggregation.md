# TASK-US007-03 — Aggregate Connector Results into Unified Context List

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US007-03 |
| User Story | US-007 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement the result aggregation step that merges `ContextChunk` lists from all successful connectors into a single flat list, enforces per-source token budget caps, attaches `degraded_sources` metadata for failed connectors, and updates `AgentState` with the unified context ready for the governance and compression nodes.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2

**File locations:**
- `src/agents/retrieval/aggregator.py` — `ContextAggregator` class
- `src/agents/nodes/retrieval_agent.py` — calls aggregator after `fetch_all` (extends TASK-US007-01)
- `tests/agents/test_context_aggregator.py`

**`ContextAggregator` responsibilities:**
1. Enforce per-source `token_budget` cap (truncate chunks from over-budget sources)
2. Flatten all source results into one `list[ContextChunk]`
3. Deduplicate by `chunk_id` (exact-match only — semantic dedup is EP-005)
4. Attach `degraded_sources` to state for downstream transparency

```python
class ContextAggregator:
    def aggregate(
        self,
        fetch_result: FetchAllResult,
        token_budget_per_source: dict[str, int],
        global_token_budget: int,
    ) -> AggregatedContext:

        chunks: list[ContextChunk] = []
        seen_chunk_ids: set[str] = set()

        # Per-source budget enforcement
        for source_id in self._source_order(fetch_result.chunks):
            source_chunks = [c for c in fetch_result.chunks if c.source_id == source_id]
            budget = token_budget_per_source.get(source_id, global_token_budget)
            accumulated = 0
            for chunk in source_chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                if accumulated + chunk.token_count > budget:
                    break
                chunks.append(chunk)
                seen_chunk_ids.add(chunk.chunk_id)
                accumulated += chunk.token_count

        # Enforce global token cap across all sources
        global_chunks: list[ContextChunk] = []
        total_tokens = 0
        for chunk in chunks:
            if total_tokens + chunk.token_count > global_token_budget:
                break
            global_chunks.append(chunk)
            total_tokens += chunk.token_count

        return AggregatedContext(
            chunks=global_chunks,
            total_token_count=total_tokens,
            source_count=len({c.source_id for c in global_chunks}),
            degraded_sources=[
                DegradedSource(
                    source_id=f.source_id,
                    error_type=f.error_type,
                    message=f.message,
                )
                for f in fetch_result.failed_sources
            ],
        )

    def _source_order(self, chunks: list[ContextChunk]) -> list[str]:
        """Preserve insertion order of source IDs from execution plan"""
        seen = dict.fromkeys(c.source_id for c in chunks)
        return list(seen)
```

**`AggregatedContext` schema:**
```python
class DegradedSource(BaseModel):
    source_id:  str
    error_type: str
    message:    str

class AggregatedContext(BaseModel):
    chunks:            list[ContextChunk]
    total_token_count: int
    source_count:      int
    degraded_sources:  list[DegradedSource]
```

**Updated `retrieval_node` return (incorporates aggregation):**
```python
aggregated = aggregator.aggregate(
    fetch_result=results,
    token_budget_per_source=plan.get("token_budget_per_source", {}),
    global_token_budget=plan.get("token_budget_total", 8000),
)

return {
    "raw_context":      [c.model_dump() for c in aggregated.chunks],
    "ranked_context":   [c.model_dump() for c in aggregated.chunks],  # ranking in EP-004
    "degraded_sources": [d.model_dump() for d in aggregated.degraded_sources],
    "current_node":     "retrieval_agent",
    "status":           ExecutionStatus.RUNNING,
}
```

Note: `degraded_sources` is added to `AgentState` TypedDict (TASK-US005-01) as `Optional[list[dict]]`.

**MCP response passthrough:** The gateway (TASK-US003-01) includes `degraded_sources` in the final `ToolCallOutput` so the AI assistant can surface a warning like *"Note: Jira connector unavailable — results may be incomplete."*

## Acceptance Criteria

- [ ] Chunks from all successful connectors appear in `AggregatedContext.chunks` as a flat list
- [ ] Per-source token budget cap is respected: chunks exceeding the source budget are truncated (not omitted entirely)
- [ ] Global token budget cap is enforced across all sources combined
- [ ] Exact-duplicate `chunk_id` values appear only once in the aggregated list
- [ ] `AggregatedContext.degraded_sources` lists every failed connector with `source_id`, `error_type`, and `message`
- [ ] Empty chunks list (all connectors failed) returns a valid `AggregatedContext` with empty `chunks` and populated `degraded_sources`
- [ ] Unit tests cover: all succeed, partial failure, all fail, per-source budget exceeded, global budget exceeded, duplicate chunk IDs

## Dependencies

- TASK-US007-01 (`FetchAllResult` as input to aggregator)
- TASK-US007-02 (`failed_sources` populated by timeout/error handling)
- TASK-US005-01 (`AgentState` TypedDict updated to include `degraded_sources`)

## Definition of Done

- [ ] `ContextAggregator` fully unit-tested with ≥ 90% branch coverage
- [ ] `degraded_sources` field added to `AgentState` TypedDict and `NODE_OUTPUT_CONTRACTS["retrieval_agent"]`
- [ ] Integration test: 2 connectors succeed + 1 times out → `degraded_sources` has 1 entry, `chunks` has results from 2 sources
- [ ] `mypy --strict` passes on `aggregator.py`
