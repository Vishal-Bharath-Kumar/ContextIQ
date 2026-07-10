# TASK-US015-01 — `RemovedChunk` Summary Schema and `AgentState.removed_chunks` Field

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US015-01 |
| User Story | US-015 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the `RemovedChunk` Pydantic model that records why a chunk was excluded from the final context set, and add `removed_chunks` and `compressed_context` to `AgentState`. This schema is the audit record consumed by EP-011 (replay trace) and the `removed_chunks` summary required by US-015 AC-3. It is shared by the exact deduplicator (TASK-US015-02), the boilerplate matcher (TASK-US015-03), and the semantic deduplicator (US-016).

## Implementation Details

**Technology:** Python 3.11+, `pydantic>=2.0`

**File locations:**
- `src/compression/schemas/removed_chunk.py` — `RemovalReason` enum and `RemovedChunk` model
- `src/agents/state.py` — `AgentState` additions
- `tests/compression/schemas/test_removed_chunk.py`

**`RemovalReason` enum:**

```python
# src/compression/schemas/removed_chunk.py
from enum import StrEnum

class RemovalReason(StrEnum):
    EXACT_DUPLICATE   = "exact_duplicate"    # identical content fingerprint
    BOILERPLATE       = "boilerplate"        # matched a configured regex rule
    SEMANTIC_NEAR_DUP = "semantic_near_dup"  # cosine similarity ≥ threshold (US-016)
```

**`RemovedChunk` model:**

```python
from pydantic import BaseModel
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

class RemovedChunk(BaseModel):
    chunk_id:        str           # ID of the chunk that was removed
    source_id:       str           # connector origin of the removed chunk
    reason:          RemovalReason
    duplicate_of:    str | None = None   # chunk_id of the retained duplicate (if applicable)
    boilerplate_rule: str | None = None  # regex rule name that matched (if applicable)
    original_content: str          # full text preserved for replay — NOT sent to model

    model_config = ConfigDict(frozen=True)
```

**`AgentState` additions:**

```python
# src/agents/state.py  (add to existing TypedDict)
from src.compression.schemas.removed_chunk import RemovedChunk

class AgentState(TypedDict, total=False):
    # ... existing fields ...

    # EP-005 additions
    compressed_context: Optional[list[RetrievedChunk]]   # output of compression_agent
    removed_chunks:     Optional[list[RemovedChunk]]     # audit trail of excluded chunks
```

**Replay trace contract:**
- `original_content` is retained in `RemovedChunk` to satisfy US-015 AC-6 and EP-011 replay requirements
- The field is explicitly excluded from the final context payload sent to the model — it is only emitted via the Kafka `StateTransitionEvent` snapshot (TASK-US015-05)
- Downstream nodes that read `compressed_context` must not access `removed_chunks[*].original_content`

## Acceptance Criteria

- [ ] `RemovedChunk` instantiation succeeds with `reason=RemovalReason.EXACT_DUPLICATE` and `duplicate_of` set
- [ ] `RemovedChunk` instantiation succeeds with `reason=RemovalReason.BOILERPLATE` and `boilerplate_rule` set
- [ ] `AgentState` contains `compressed_context: Optional[list[RetrievedChunk]]` and `removed_chunks: Optional[list[RemovedChunk]]`
- [ ] `RemovedChunk.model_dump()` serialises to JSON-compatible dict — `original_content` is present
- [ ] `model_config = ConfigDict(frozen=True)` — post-construction mutation raises `ValidationError`

## Dependencies

- TASK-US012-01 (`RetrievedChunk` — `removed_chunk.duplicate_of` references a `chunk_id`)
- TASK-US005-01 (`AgentState` TypedDict — extended here)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `RemovedChunk` is the single canonical removed-chunk type used across US-015 and US-016
- [ ] Unit tests cover: valid construction for each `RemovalReason`, `model_dump()` round-trip
- [ ] `mypy --strict` passes; no `ruff` lint errors
