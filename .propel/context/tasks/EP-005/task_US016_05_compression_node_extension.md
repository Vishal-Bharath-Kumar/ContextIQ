# TASK-US016-05 — `compression_node` Extension and `AgentState.consolidated_sources`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US016-05 |
| User Story | US-016 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Extend `compression_node()` (TASK-US015-05) to run `SemanticDeduplicator` as a second compression stage after `RuleBasedCompressor`. Add `consolidated_sources` to `AgentState` to record which source IDs were absorbed into retained chunks. Append semantic `RemovedChunk` records to the existing `removed_chunks` list so the Kafka replay snapshot (TASK-US015-05) contains the full audit trail.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`

**File locations:**
- `src/agents/nodes/compression_node.py` — extended (extends TASK-US015-05)
- `src/agents/state.py` — `consolidated_sources` field added
- `tests/agents/nodes/test_compression_node_semantic.py`

**`AgentState` addition:**

```python
# src/agents/state.py  (add to existing EP-005 block)
consolidated_sources: Optional[dict[str, list[str]]]
    # retained_chunk_id → list of source_ids that were merged into it
    # e.g. {"chunk-abc": ["confluence", "github"]}
    # None on the happy path when no semantic merges occurred
```

**Extended `compression_node()`:**

```python
# src/agents/nodes/compression_node.py  (extends TASK-US015-05)
from src.compression.rule_based_compressor      import RuleBasedCompressor
from src.compression.semantic.semantic_deduplicator import SemanticDeduplicator
from src.agents.state                           import AgentState, ExecutionStatus

_rule_compressor  = RuleBasedCompressor()    # module-level singletons
_semantic_dedup   = SemanticDeduplicator()

async def compression_node(state: AgentState) -> dict:
    ranked_context = state.get("ranked_context") or []

    # Stage 1: rule-based (exact dedup + boilerplate) — US-015
    after_rules, rule_removed = _rule_compressor.compress(ranked_context)

    # Stage 2: semantic near-duplicate merging — US-016
    after_semantic, semantic_removed, consolidated = _semantic_dedup.deduplicate(after_rules)

    all_removed = rule_removed + semantic_removed

    return {
        "compressed_context":  after_semantic,
        "removed_chunks":      all_removed,
        "consolidated_sources": consolidated if consolidated else None,
        "ranked_context":      after_semantic,   # pass-through for routing_agent
        "current_node":        "compression_agent",
        "status":              ExecutionStatus.RUNNING,
    }
```

**15% token reduction validation (US-016 AC-5):**

The existing token-reduction test in TASK-US015-04 validates ≥ 10% for rule-based alone. Add a separate integration test that validates the combined two-stage pipeline achieves ≥ 15% on a fixture with redundant multi-source content:

```python
# tests/agents/nodes/test_compression_node_semantic.py
def test_combined_compression_reduces_tokens_by_15_percent(mock_semantic_embedder):
    """Mock embedder returns near-identical vectors for chunks from different sources."""
    from src.retrieval.ranking.filters import count_tokens
    chunks = _make_redundant_multi_source_chunks(50)   # 20% boilerplate + 30% near-dups

    async def _run():
        state = {"ranked_context": chunks}
        result = await compression_node(state)
        return result

    result    = asyncio.run(_run())
    original  = sum(count_tokens(c.content) for c in chunks)
    compressed = sum(count_tokens(c.content) for c in result["compressed_context"])
    reduction  = (original - compressed) / original
    assert reduction >= 0.15, f"Combined reduction {reduction:.1%} < 15%"
```

**`consolidated_sources` state semantics:**
- `None` when no semantic merges occurred (common case for low-overlap retrieval sets)
- Non-empty dict when ≥ 1 near-duplicate cluster was merged
- Downstream nodes (`routing_agent`, `compression_agent` in future US-017) must treat `None` as equivalent to `{}`

**Kafka snapshot update:**
The `removed_chunks_snapshot` in `StateTransitionEvent` (TASK-US015-05) captures `all_removed` — no additional Kafka schema change is needed. The semantic `RemovedChunk` records carry `reason = SEMANTIC_NEAR_DUP`, which the Replay Service uses to distinguish the two compression stages.

## Acceptance Criteria

- [ ] `compression_node()` runs `RuleBasedCompressor` first, then `SemanticDeduplicator` on its output
- [ ] `AgentState.removed_chunks` contains records from both compression stages after the node runs
- [ ] `AgentState.consolidated_sources` is `None` when no semantic merges occurred
- [ ] `AgentState.consolidated_sources` maps `chunk_id → [source_id, ...]` for each merged cluster
- [ ] Combined pipeline achieves ≥ 15% token reduction on the redundant multi-source test fixture
- [ ] `_rule_compressor` and `_semantic_dedup` are module-level singletons — not re-instantiated per call

## Dependencies

- TASK-US015-05 (`compression_node()` — extended here)
- TASK-US016-04 (`SemanticDeduplicator.deduplicate()`)
- TASK-US015-01 (`AgentState.compressed_context`, `removed_chunks` — `consolidated_sources` added here)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `compression_node` runs both stages in the correct order — no stage can be skipped by accident
- [ ] Integration test asserts ≥ 15% combined token reduction on the multi-source fixture
- [ ] `mypy --strict` passes; no `ruff` lint errors
