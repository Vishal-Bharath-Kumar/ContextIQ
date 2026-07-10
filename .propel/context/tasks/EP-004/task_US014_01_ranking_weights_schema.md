# TASK-US014-01 — Extend `RetrievedChunk` with Pre-Merge Score Fields and `RankingWeights` Config Schema

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US014-01 |
| User Story | US-014 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Extend `RetrievedChunk` (TASK-US012-01) with optional `vector_score` and `keyword_score` fields so the combined scoring formula (vector 60% + keyword 20% + recency 20%) can use the original per-signal values. Update the RRF merger (TASK-US012-04) to populate both fields when a chunk appears in both search paths. Define `RankingWeights` and the per-intent weight table that drives the governance node (TASK-US014-05).

## Implementation Details

**Technology:** Python 3.11+, `pydantic>=2.0`

**File locations:**
- `src/retrieval/schemas/retrieved_chunk.py` — `RetrievedChunk` extension (extends TASK-US012-01)
- `src/retrieval/ranking/weights.py` — `RankingWeights` model and `INTENT_WEIGHT_TABLE`
- `src/retrieval/fusion/rrf.py` — `ReciprocRankFusion.merge()` updated to preserve both scores (extends TASK-US012-04)
- `tests/retrieval/ranking/test_ranking_weights.py`

**`RetrievedChunk` extension:**

```python
# src/retrieval/schemas/retrieved_chunk.py  (extend existing model — do NOT redefine)
class RetrievedChunk(BaseModel):
    # --- existing fields (TASK-US012-01, unchanged) ---
    chunk_id:    str
    source_id:   str
    content:     str
    score:       float              # RRF score post-merge; individual score pre-merge
    search_mode: Literal["vector", "keyword", "rrf"] = "rrf"
    metadata:    ChunkMetadata

    # --- US-014 additions ---
    vector_score:  float | None = None   # cosine similarity from Qdrant (before RRF)
    keyword_score: float | None = None   # normalised BM25 score from OpenSearch (before RRF)

    model_config = ConfigDict(frozen=True)
```

**RRF merger update — preserve both pre-merge scores:**

```python
# src/retrieval/fusion/rrf.py  (extend merge() in ReciprocRankFusion — TASK-US012-04)

# When building best_chunk, track scores by search_mode:
vector_scores:  dict[str, float] = {}
keyword_scores: dict[str, float] = {}

for ranked_list in ranked_lists:
    for rank, chunk in enumerate(ranked_list, start=1):
        cid = chunk.chunk_id
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (self._k + rank)
        if chunk.search_mode == "vector":
            vector_scores[cid]  = chunk.score
        elif chunk.search_mode == "keyword":
            keyword_scores[cid] = chunk.score
        if cid not in best_chunk or chunk.score > best_chunk[cid].score:
            best_chunk[cid] = chunk

# Reconstruct with both scores populated:
merged = [
    best_chunk[cid].model_copy(update={
        "score":         rrf_score,
        "search_mode":   "rrf",
        "vector_score":  vector_scores.get(cid),
        "keyword_score": keyword_scores.get(cid),
    })
    for cid, rrf_score in rrf_scores.items()
]
```

**`RankingWeights` model:**

```python
# src/retrieval/ranking/weights.py
from pydantic import BaseModel, Field, model_validator

class RankingWeights(BaseModel):
    vector_weight:  float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    recency_weight: float = Field(default=0.2, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "RankingWeights":
        total = self.vector_weight + self.keyword_weight + self.recency_weight
        if not (0.999 < total < 1.001):
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")
        return self
```

**Per-intent weight table (AIR-011 canonical defaults):**

```python
from src.agents.schemas.intent import IntentType

INTENT_WEIGHT_TABLE: dict[IntentType, RankingWeights] = {
    IntentType.DEBUGGING:    RankingWeights(vector_weight=0.5, keyword_weight=0.3, recency_weight=0.2),
    IntentType.CODE_GEN:     RankingWeights(vector_weight=0.7, keyword_weight=0.1, recency_weight=0.2),
    IntentType.ARCHITECTURE: RankingWeights(vector_weight=0.7, keyword_weight=0.1, recency_weight=0.2),
    IntentType.DOCS:         RankingWeights(vector_weight=0.6, keyword_weight=0.2, recency_weight=0.2),
    IntentType.INCIDENT:     RankingWeights(vector_weight=0.3, keyword_weight=0.5, recency_weight=0.2),
    IntentType.METRICS:      RankingWeights(vector_weight=0.2, keyword_weight=0.6, recency_weight=0.2),
    IntentType.CODE_REVIEW:  RankingWeights(vector_weight=0.6, keyword_weight=0.2, recency_weight=0.2),
    IntentType.GENERAL:      RankingWeights(vector_weight=0.6, keyword_weight=0.2, recency_weight=0.2),
}
DEFAULT_WEIGHTS = RankingWeights()   # 0.6 / 0.2 / 0.2
```

## Acceptance Criteria

- [ ] `RetrievedChunk` instantiation succeeds with `vector_score=None` and `keyword_score=None` (both optional)
- [ ] `rrf_merge()` populates `vector_score` for chunks that appeared in the Qdrant list
- [ ] `rrf_merge()` populates `keyword_score` for chunks that appeared in the OpenSearch list
- [ ] A chunk appearing in both lists has both fields non-`None`
- [ ] `RankingWeights(vector_weight=0.5, keyword_weight=0.6, recency_weight=0.2)` raises `ValidationError` (sum > 1)
- [ ] All 8 intent types are present in `INTENT_WEIGHT_TABLE`
- [ ] `INTENT_WEIGHT_TABLE` values all pass the `weights_sum_to_one` validator

## Dependencies

- TASK-US012-01 (`RetrievedChunk` — extended here; `frozen=True` requires `model_copy()` for updates)
- TASK-US012-04 (`ReciprocRankFusion.merge()` — score-tracking logic extended)
- TASK-US009-03 (`IntentType` enum — keys for `INTENT_WEIGHT_TABLE`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `RetrievedChunk` extension is backward-compatible — `vector_score` and `keyword_score` default to `None`
- [ ] All existing TASK-US012-04 unit tests continue to pass
- [ ] `mypy --strict` passes; no `ruff` lint errors
