# TASK-US012-04 — Reciprocal Rank Fusion Merger and Top-K Selection

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US012-04 |
| User Story | US-012 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ReciprocRankFusion`, the stateless class that takes two independently-ranked `RetrievedChunk` lists (from Qdrant ANN and OpenSearch BM25), computes RRF scores, and returns the unified top-K result list ordered by descending RRF score. This is the core merge step specified in AIR-010 (hybrid search).

## Implementation Details

**Technology:** Python 3.11+

**File locations:**
- `src/retrieval/fusion/rrf.py` — `ReciprocRankFusion` class and `rrf_merge()` convenience function
- `tests/retrieval/fusion/test_rrf.py`

**RRF formula:**

For a chunk appearing in ranked list $l$ at rank position $r_l$ (1-indexed), the RRF score is:

$$\text{RRF}(d) = \sum_{l \in L} \frac{1}{k + r_l(d)}$$

where $k$ is a smoothing constant (default $k = 60$, as per the original Cormack et al. paper and the value used in Elasticsearch/OpenSearch hybrid search).

**Implementation:**

```python
# src/retrieval/fusion/rrf.py
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

DEFAULT_K:     int = 60    # RRF smoothing constant (Cormack et al., 2009)
DEFAULT_TOP_K: int = 20    # returned result set size (US-012 AC-3)

class ReciprocRankFusion:
    def __init__(self, k: int = DEFAULT_K, top_k: int = DEFAULT_TOP_K) -> None:
        self._k      = k
        self._top_k  = top_k

    def merge(
        self,
        *ranked_lists: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Merge N ranked lists into one top-K list using RRF scoring.

        Chunks with the same `chunk_id` across lists are deduplicated;
        the highest-scoring original chunk is retained for the content payload.
        """
        rrf_scores: dict[str, float]        = {}
        best_chunk: dict[str, RetrievedChunk] = {}

        for ranked_list in ranked_lists:
            for rank, chunk in enumerate(ranked_list, start=1):
                cid = chunk.chunk_id
                rrf_scores[cid]  = rrf_scores.get(cid, 0.0) + 1.0 / (self._k + rank)
                # Keep the instance with the higher individual score for the payload
                if cid not in best_chunk or chunk.score > best_chunk[cid].score:
                    best_chunk[cid] = chunk

        # Reconstruct chunks with RRF score, mark search_mode = "rrf"
        merged = [
            best_chunk[cid].model_copy(update={"score": rrf_score, "search_mode": "rrf"})
            for cid, rrf_score in rrf_scores.items()
        ]

        merged.sort(key=lambda c: c.score, reverse=True)
        return merged[: self._top_k]


def rrf_merge(
    vector_results:  list[RetrievedChunk],
    keyword_results: list[RetrievedChunk],
    k:      int = DEFAULT_K,
    top_k:  int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Convenience wrapper for two-list hybrid search merge."""
    return ReciprocRankFusion(k=k, top_k=top_k).merge(vector_results, keyword_results)
```

**Score semantics after merge:**
- RRF scores are small positive floats (e.g. `0.016` for rank 1 with k=60)
- They are NOT normalised back to `[0.0, 1.0]` — downstream nodes receive the raw RRF value and treat it as a relative ranking signal, not an absolute probability
- `search_mode = "rrf"` marks chunks as merged so downstream code can distinguish pre- and post-merge chunks

**Deduplication behaviour:**
- A chunk appearing in both Qdrant and OpenSearch results accumulates RRF score from both lists (this is the desired fusion signal — appearing in both is strong evidence of relevance)
- The content payload is taken from the instance with the higher individual score (typically the vector result, which carries a cosine similarity)

## Acceptance Criteria

- [ ] A chunk ranked #1 in both lists receives a higher RRF score than a chunk ranked #1 in only one list
- [ ] `rrf_merge(qdrant_results=[], keyword_results=[])` returns `[]`
- [ ] `rrf_merge` with `top_k=5` returns exactly 5 chunks when both lists contain ≥ 5 distinct chunks
- [ ] Chunks present in both lists are deduplicated — one entry per `chunk_id` in the output
- [ ] `search_mode` is `"rrf"` for all chunks in the merged output
- [ ] RRF score of a chunk ranked #1 (k=60) equals `1/61 ≈ 0.01639` — asserted in unit tests
- [ ] `DEFAULT_K = 60` and `DEFAULT_TOP_K = 20` are the only sources of truth for these constants

## Dependencies

- TASK-US012-01 (`RetrievedChunk` — `model_copy(update=...)` requires `frozen=True` + Pydantic v2)
- TASK-US012-02 (Qdrant client output is one of the input ranked lists)
- TASK-US012-03 (OpenSearch client output is the other ranked list)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit tests cover: dual-list merge, single-list degenerate case, empty lists, top-K truncation, cross-list deduplication, RRF score arithmetic
- [ ] `mypy --strict` passes; no `ruff` lint errors
