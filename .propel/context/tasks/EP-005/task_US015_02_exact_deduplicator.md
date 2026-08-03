# TASK-US015-02 — Exact-Duplicate Deduplicator (Content Fingerprint)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US015-02 |
| User Story | US-015 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `ExactDeduplicator`, which removes chunks whose normalised text content is byte-for-byte identical to a previously seen chunk in the same context set. Deduplication uses a SHA-256 content fingerprint rather than `chunk_id` to catch cross-source duplicates — the same file indexed in both Qdrant (GitHub) and OpenSearch (Confluence) produces different `chunk_id` values but identical content after normalisation.

## Implementation Details

**Technology:** Python 3.11+, `hashlib` (stdlib)

**File locations:**
- `src/compression/dedup/exact_deduplicator.py` — `ExactDeduplicator` class and `content_fingerprint()`
- `tests/compression/dedup/test_exact_deduplicator.py`

**Content normalisation and fingerprint:**

```python
# src/compression/dedup/exact_deduplicator.py
import hashlib, re

def _normalise(text: str) -> str:
    """Strip leading/trailing whitespace and collapse internal whitespace runs.

    Normalisation makes fingerprinting robust to trivial formatting differences
    (trailing newlines, mixed indentation) without altering semantic content.
    """
    text = text.strip()
    text = re.sub(r"[ \t]+", " ", text)      # collapse horizontal whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)   # collapse excessive blank lines
    return text

def content_fingerprint(text: str) -> str:
    """Return a 16-char hex SHA-256 of the normalised content."""
    return hashlib.sha256(_normalise(text).encode()).hexdigest()[:16]
```

**`ExactDeduplicator`:**

```python
from src.retrieval.schemas.retrieved_chunk  import RetrievedChunk
from src.compression.schemas.removed_chunk  import RemovedChunk, RemovalReason

class ExactDeduplicator:
    def deduplicate(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[list[RetrievedChunk], list[RemovedChunk]]:
        """Remove exact-duplicate chunks by content fingerprint.

        The first occurrence (highest-ranked, as input is pre-sorted by score)
        is always retained; subsequent duplicates are removed.

        Returns: (kept_chunks, removed_chunks)
        """
        seen_fingerprints: dict[str, str] = {}   # fingerprint → retained chunk_id
        kept:    list[RetrievedChunk] = []
        removed: list[RemovedChunk]   = []

        for chunk in chunks:
            fp = content_fingerprint(chunk.content)
            if fp in seen_fingerprints:
                removed.append(RemovedChunk(
                    chunk_id         = chunk.chunk_id,
                    source_id        = chunk.source_id,
                    reason           = RemovalReason.EXACT_DUPLICATE,
                    duplicate_of     = seen_fingerprints[fp],
                    original_content = chunk.content,
                ))
            else:
                seen_fingerprints[fp] = chunk.chunk_id
                kept.append(chunk)

        return kept, removed
```

**Ordering guarantee:**
- Input `chunks` is assumed to be sorted descending by `score` (output of `ContextRanker`)
- The first occurrence of a fingerprint is always retained, so the highest-scored copy survives deduplication
- If two chunks have identical content but different `source_id`, the one with the higher relevance score is kept

## Acceptance Criteria

- [ ] Two chunks with identical content (same text, different `source_id`) — only the first (higher score) is retained
- [ ] `ExactDeduplicator` returns `(all_chunks, [])` when every chunk is unique
- [ ] The `removed` list entry has `reason = RemovalReason.EXACT_DUPLICATE` and `duplicate_of` pointing to the retained chunk's `chunk_id`
- [ ] Normalisation: chunks differing only in trailing whitespace or extra blank lines are treated as duplicates
- [ ] `content_fingerprint` is deterministic — same content always produces the same fingerprint
- [ ] `ExactDeduplicator` does not mutate the input list

## Dependencies

- TASK-US015-01 (`RemovedChunk`, `RemovalReason.EXACT_DUPLICATE`)
- TASK-US012-01 (`RetrievedChunk.content` and `.chunk_id`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 90% for `src/compression/dedup/exact_deduplicator.py`
- [ ] Tests cover: two identical chunks, three chunks with one duplicate, all unique, whitespace-normalisation dedup, cross-source dedup
- [ ] `mypy --strict` passes; no `ruff` lint errors
