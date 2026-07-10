# TASK-US014-04 — `ContextRanker` Orchestrator and 200 ms Benchmark

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US014-04 |
| User Story | US-014 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend / Performance |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ContextRanker`, the stateless class that orchestrates the full re-ranking pipeline: score each chunk with the combined formula, filter below threshold, sort descending, and truncate to token budget. Add a CI benchmark asserting the complete pipeline completes in < 200 ms for a realistic 1 000-chunk input. `ContextRanker` is the single entry point consumed by `governance_node` (TASK-US014-05).

## Implementation Details

**Technology:** Python 3.11+, `pytest-benchmark`

**File locations:**
- `src/retrieval/ranking/ranker.py` — `ContextRanker` class
- `tests/retrieval/ranking/test_ranker.py`
- `tests/retrieval/ranking/test_ranker_benchmark.py`

**`ContextRanker`:**

```python
# src/retrieval/ranking/ranker.py
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk
from src.retrieval.ranking.weights         import RankingWeights, DEFAULT_WEIGHTS
from src.retrieval.ranking.scorer          import calculate_combined_score
from src.retrieval.ranking.filters         import filter_below_threshold, truncate_to_token_budget
from src.retrieval.ranking.config          import DEFAULT_RELEVANCE_THRESHOLD

class ContextRanker:
    def __init__(
        self,
        weights:   RankingWeights = DEFAULT_WEIGHTS,
        threshold: float          = DEFAULT_RELEVANCE_THRESHOLD,
    ) -> None:
        self._weights   = weights
        self._threshold = threshold

    def rank(
        self,
        chunks:       list[RetrievedChunk],
        token_budget: int,
    ) -> list[RetrievedChunk]:
        """Score, filter, sort, and truncate a raw chunk list.

        Steps:
          1. Compute combined score for each chunk (vector + keyword + recency)
          2. Rebuild chunks with updated `score` field (model_copy — frozen model)
          3. Filter below threshold
          4. Sort descending by score
          5. Truncate to token budget
        """
        if not chunks:
            return []

        # Step 1–2: score and rebuild (pure computation — no I/O)
        scored = [
            chunk.model_copy(update={"score": calculate_combined_score(chunk, self._weights)})
            for chunk in chunks
        ]

        # Step 3: threshold filter
        filtered = filter_below_threshold(scored, self._threshold)

        # Step 4: sort
        filtered.sort(key=lambda c: c.score, reverse=True)

        # Step 5: token budget truncation
        return truncate_to_token_budget(filtered, token_budget)
```

**200 ms benchmark — 1 000-chunk input:**

```python
# tests/retrieval/ranking/test_ranker_benchmark.py
import pytest
from datetime import datetime, timezone, timedelta
from src.retrieval.ranking.ranker  import ContextRanker
from src.retrieval.ranking.weights import DEFAULT_WEIGHTS
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk, ChunkMetadata

def _make_chunks(n: int) -> list[RetrievedChunk]:
    now = datetime.now(timezone.utc)
    return [
        RetrievedChunk(
            chunk_id     = f"chunk-{i:04d}",
            source_id    = "github",
            content      = "def foo(): pass  " * 20,   # ~80 tokens each
            score        = 0.01639,                     # RRF rank-1 score (k=60)
            search_mode  = "rrf",
            vector_score = 0.8,
            keyword_score = 0.6,
            metadata     = ChunkMetadata(
                file_path  = f"src/module_{i}.py",
                timestamp  = now - timedelta(days=i % 90),
                author     = "dev",
            ),
        )
        for i in range(n)
    ]

@pytest.mark.benchmark(max_time=0.2)
def test_ranker_200ms_benchmark(benchmark):
    ranker = ContextRanker()
    chunks = _make_chunks(1_000)

    result = benchmark(lambda: ranker.rank(chunks, token_budget=8_000))

    assert isinstance(result, list)
    assert all(c.score >= 0.5 for c in result)
```

**Performance analysis:**
- Step 1–2 (scoring): 1 000 × [2 multiplications + 1 `exp()` + 1 `model_copy()`] ≈ 10–20 ms
- Step 3 (filter): O(n) list comprehension ≈ < 1 ms
- Step 4 (sort): O(n log n) Timsort on 1 000 items ≈ < 1 ms
- Step 5 (truncation + tokenisation): `tiktoken.encode()` for each kept chunk — bottleneck; if > 100 ms, add `lru_cache` on `count_tokens` keyed on `chunk_id`

**Mutability note:** `RetrievedChunk` is frozen (`ConfigDict(frozen=True)`). `model_copy(update=...)` creates a new instance with the updated `score` — the original `raw_context` chunks in `AgentState` are not mutated.

## Acceptance Criteria

- [ ] `ContextRanker.rank([])` returns `[]`
- [ ] All chunks in the output have `score >= DEFAULT_RELEVANCE_THRESHOLD`
- [ ] Output is ordered descending by `score` (first chunk has the highest score)
- [ ] Output total token count does not exceed `token_budget`
- [ ] `ContextRanker` does not mutate the input `chunks` list or any `RetrievedChunk` instance
- [ ] CI benchmark passes: `rank()` on 1 000 chunks completes in < 200 ms

## Dependencies

- TASK-US014-01 (`RankingWeights`, `RetrievedChunk.model_copy()` for frozen model)
- TASK-US014-02 (`calculate_combined_score()`)
- TASK-US014-03 (`filter_below_threshold()`, `truncate_to_token_budget()`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `ContextRanker` is the single ranking entry point — no scoring logic in `governance_node`
- [ ] Unit tests cover: empty input, all-below-threshold, budget-exact truncation, sort order
- [ ] Benchmark test included in CI; fails build if p99 > 200 ms on the 1 000-chunk fixture
- [ ] `mypy --strict` passes; no `ruff` lint errors
