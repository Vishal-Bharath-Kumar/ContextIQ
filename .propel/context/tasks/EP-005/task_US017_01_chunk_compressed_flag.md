# TASK-US017-01 — Extend `RetrievedChunk` with `compressed` Flag and `original_token_count`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US017-01 |
| User Story | US-017 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Extend `RetrievedChunk` (TASK-US012-01) with two optional fields needed for LLM summarisation: `compressed` marks whether the chunk content was replaced by an LLM-generated summary, and `original_token_count` records the pre-summarisation token count for audit, cost estimation, and the 60% reduction eval harness. Both fields are optional and backward-compatible with all existing construction sites.

## Implementation Details

**Technology:** Python 3.11+, `pydantic>=2.0`

**File locations:**
- `src/retrieval/schemas/retrieved_chunk.py` — `RetrievedChunk` extension (extends TASK-US014-01)
- `tests/retrieval/schemas/test_retrieved_chunk_compression.py`

**`RetrievedChunk` extension:**

```python
# src/retrieval/schemas/retrieved_chunk.py  (extend — do NOT redefine existing fields)
class RetrievedChunk(BaseModel):
    # --- existing fields (unchanged) ---
    chunk_id:           str
    source_id:          str
    content:            str
    score:              float
    search_mode:        Literal["vector", "keyword", "rrf"] = "rrf"
    metadata:           ChunkMetadata
    vector_score:       float | None = None
    keyword_score:      float | None = None

    # --- US-017 additions ---
    compressed:           bool      = False
    # Token count of the original content before LLM summarisation.
    # None when the chunk has never been summarised.
    original_token_count: int | None = None

    model_config = ConfigDict(frozen=True)
```

**Construction contract for summarised chunks:**

When `ChunkSummarizer` (TASK-US017-04) replaces a chunk's content with a summary, it uses `model_copy()`:

```python
summarised_chunk = chunk.model_copy(update={
    "content":              summary_text,
    "compressed":           True,
    "original_token_count": original_token_count,
})
```

The `chunk_id`, `source_id`, `score`, `metadata`, and all relevance signals are preserved. Only `content`, `compressed`, and `original_token_count` change.

**Downstream contract:**
- Nodes that read `RetrievedChunk.content` for prompt assembly must treat `compressed=True` as a signal that the content is a summary, not the verbatim source
- Replay Service (EP-011) uses `original_token_count` to reconstruct cost estimates without re-tokenising
- `original_token_count = None` for chunks that were never summarised (the common case); consumers must handle `None` without `AttributeError`

## Acceptance Criteria

- [ ] `RetrievedChunk` instantiation with no new fields succeeds (`compressed=False`, `original_token_count=None`)
- [ ] `chunk.model_copy(update={"compressed": True, "original_token_count": 800})` produces a new frozen instance with updated fields
- [ ] `compressed=True` and `original_token_count=None` is a valid combination (chunk flagged but count not yet set)
- [ ] `model_dump()` serialises `compressed` and `original_token_count` correctly for Kafka payloads
- [ ] All existing `RetrievedChunk` construction sites continue to pass without modification

## Dependencies

- TASK-US012-01 (`RetrievedChunk` base model — extended here)
- TASK-US014-01 (`vector_score`/`keyword_score` added in that task — compatible extension pattern)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Extension is backward-compatible — no existing test requires modification
- [ ] Unit tests cover: default values, `model_copy` round-trip, `model_dump()` serialisation
- [ ] `mypy --strict` passes; no `ruff` lint errors
