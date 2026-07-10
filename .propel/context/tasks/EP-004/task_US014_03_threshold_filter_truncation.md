# TASK-US014-03 — Relevance Threshold Filter and Token-Budget Truncation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US014-03 |
| User Story | US-014 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the two post-scoring reduction functions: `filter_below_threshold()` removes chunks whose combined score falls below the configurable minimum relevance threshold (default 0.5), and `truncate_to_token_budget()` cuts the remaining sorted list to fit within the execution plan's total token budget. Both functions are pure, stateless, and consumed by `ContextRanker` (TASK-US014-04).

## Implementation Details

**Technology:** Python 3.11+, `tiktoken`

**File locations:**
- `src/retrieval/ranking/filters.py` — `filter_below_threshold()`, `truncate_to_token_budget()`
- `src/retrieval/ranking/config.py` — `DEFAULT_RELEVANCE_THRESHOLD` constant
- `tests/retrieval/ranking/test_filters.py`

**Config constant:**

```python
# src/retrieval/ranking/config.py
DEFAULT_RELEVANCE_THRESHOLD: float = 0.5   # US-014 AC-2
```

**`filter_below_threshold()`:**

```python
# src/retrieval/ranking/filters.py
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk
from src.retrieval.ranking.config          import DEFAULT_RELEVANCE_THRESHOLD

def filter_below_threshold(
    chunks:    list[RetrievedChunk],
    threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
) -> list[RetrievedChunk]:
    """Exclude chunks whose `score` is strictly below `threshold`.

    Operates on the `score` field, which must already reflect the combined
    score written by `ContextRanker` before this function is called.
    """
    return [c for c in chunks if c.score >= threshold]
```

**`truncate_to_token_budget()`:**

Token counting reuses the `tiktoken` singleton established in TASK-US010-04 to avoid loading the encoding model multiple times.

```python
import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")   # module-level singleton

def count_tokens(text: str) -> int:
    return len(_enc.encode(text))

def truncate_to_token_budget(
    chunks: list[RetrievedChunk],
    budget: int,
) -> list[RetrievedChunk]:
    """Return the longest prefix of `chunks` that fits within `budget` tokens.

    Chunks are assumed to be pre-sorted by descending score so the
    highest-relevance items are always retained.
    Only complete chunks are included — no partial-content chunks.
    """
    kept:  list[RetrievedChunk] = []
    used:  int = 0
    for chunk in chunks:
        tokens = count_tokens(chunk.content)
        if used + tokens > budget:
            break
        kept.append(chunk)
        used += tokens
    return kept
```

**Relationship to TASK-US010-04 `truncate_to_budget()`:**

TASK-US010-04 operates on `list[str]` (raw text chunks from a single connector, pre-RRF). This task's `truncate_to_token_budget()` operates on `list[RetrievedChunk]` (post-RRF, cross-source, post-scoring). They are complementary, not duplicates — do NOT merge them.

**Token count caching:**
`tiktoken.encode()` is deterministic for the same content string. If profiling shows tokenisation is a bottleneck for large chunk lists, a `functools.lru_cache` on `count_tokens` can be added — deferred until the 200 ms benchmark in TASK-US014-04 flags it.

## Acceptance Criteria

- [ ] `filter_below_threshold([chunk(score=0.4), chunk(score=0.5), chunk(score=0.6)], 0.5)` returns the two chunks with score ≥ 0.5
- [ ] `filter_below_threshold(chunks, threshold=0.0)` returns all chunks
- [ ] `filter_below_threshold([], 0.5)` returns `[]`
- [ ] `truncate_to_token_budget` returns only complete chunks — no partial-content entries
- [ ] A single chunk whose token count exceeds `budget` results in `[]` (not a RuntimeError)
- [ ] `DEFAULT_RELEVANCE_THRESHOLD = 0.5` is the only threshold literal in the codebase — no inline `0.5` in ranker or node code

## Dependencies

- TASK-US012-01 (`RetrievedChunk.score` and `.content` fields)
- TASK-US010-04 (`tiktoken` encoding singleton — `count_tokens` follows same pattern)
- TASK-US014-04 (`ContextRanker` — consumes both functions)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 90% for `src/retrieval/ranking/filters.py`
- [ ] Tests cover: threshold boundary (equal, below, above), empty input, budget-exact fit, single oversized chunk
- [ ] `mypy --strict` passes; no `ruff` lint errors
