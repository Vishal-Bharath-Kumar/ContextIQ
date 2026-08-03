# TASK-US014-02 — Combined Score Calculator with Recency Decay Signal

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US014-02 |
| User Story | US-014 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `calculate_combined_score()`, the pure function that produces a single relevance score for a `RetrievedChunk` by combining the vector similarity signal, keyword match signal, and time-based recency decay using the configured `RankingWeights`. Handle gracefully the cases where only one signal is available (SEMANTIC or BM25 strategy paths) by redistributing the missing signal's weight proportionally.

## Implementation Details

**Technology:** Python 3.11+, `math` (stdlib), `datetime` (stdlib)

**File locations:**
- `src/retrieval/ranking/scorer.py` — `calculate_combined_score()`, `calculate_recency_score()`, `_redistribute_weights()`
- `tests/retrieval/ranking/test_scorer.py`

**Recency decay function:**

```python
# src/retrieval/ranking/scorer.py
import math
from datetime import datetime, timezone

RECENCY_HALF_LIFE_DAYS: float = 30.0   # score halves every 30 days

def calculate_recency_score(timestamp: datetime) -> float:
    """Return a [0.0, 1.0] recency signal using exponential decay.

    Score = 1.0 for age = 0 days; ≈ 0.5 at 30 days; ≈ 0.25 at 60 days.
    """
    now       = datetime.now(timezone.utc)
    ts_aware  = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
    age_days  = max((now - ts_aware).total_seconds() / 86_400, 0.0)
    decay_rate = math.log(2) / RECENCY_HALF_LIFE_DAYS
    return math.exp(-decay_rate * age_days)
```

**Weight redistribution when a signal is absent:**

When a chunk was retrieved by only one search path (SEMANTIC → no `keyword_score`; BM25 → no `vector_score`), the missing signal's weight is redistributed to the available signal:

```python
def _redistribute_weights(
    weights:       "RankingWeights",
    has_vector:    bool,
    has_keyword:   bool,
) -> tuple[float, float, float]:
    """Return (effective_v, effective_k, effective_r) summing to 1.0."""
    if has_vector and has_keyword:
        return weights.vector_weight, weights.keyword_weight, weights.recency_weight

    if has_vector and not has_keyword:
        # keyword_weight folded into vector_weight
        total_non_recency = weights.vector_weight + weights.keyword_weight
        return total_non_recency, 0.0, weights.recency_weight

    if has_keyword and not has_vector:
        # vector_weight folded into keyword_weight
        total_non_recency = weights.vector_weight + weights.keyword_weight
        return 0.0, total_non_recency, weights.recency_weight

    # Neither score available — fall back to RRF score as base signal
    return 1.0 - weights.recency_weight, 0.0, weights.recency_weight
```

**`calculate_combined_score()` function:**

```python
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk
from src.retrieval.ranking.weights         import RankingWeights

def calculate_combined_score(chunk: RetrievedChunk, weights: RankingWeights) -> float:
    """Compute the weighted combined relevance score for a single chunk.

    Returns a float in approximately [0.0, 1.0].
    (May slightly exceed 1.0 due to RRF score range; callers should clamp if needed.)
    """
    has_vector  = chunk.vector_score  is not None
    has_keyword = chunk.keyword_score is not None
    eff_v, eff_k, eff_r = _redistribute_weights(weights, has_vector, has_keyword)

    vector_signal  = (chunk.vector_score  or 0.0) * eff_v
    keyword_signal = (chunk.keyword_score or 0.0) * eff_k

    # For pure-RRF chunks where both individual scores are None, use chunk.score as base
    if not has_vector and not has_keyword:
        base_signal = chunk.score * eff_v
    else:
        base_signal = vector_signal + keyword_signal

    recency_signal = calculate_recency_score(chunk.metadata.timestamp) * eff_r
    return base_signal + recency_signal
```

**Score range notes:**
- Individual scores (`vector_score`, `keyword_score`) are normalised to `[0.0, 1.0]` by their respective clients
- Recency score is always `[0.0, 1.0]`
- Combined score is therefore `[0.0, 1.0]` and can be directly compared against the filter threshold

## Acceptance Criteria

- [ ] `calculate_recency_score(now)` returns `1.0` for a timestamp at the current moment
- [ ] `calculate_recency_score(30 days ago)` returns `0.5` (± 0.001 tolerance for float arithmetic)
- [ ] `calculate_recency_score(60 days ago)` returns `0.25` (± 0.001)
- [ ] `calculate_combined_score` with default weights (0.6/0.2/0.2) and a chunk with `vector_score=1.0`, `keyword_score=1.0`, timestamp=now returns `≈ 1.0`
- [ ] `calculate_combined_score` with a SEMANTIC-only chunk (`keyword_score=None`) redistributes keyword weight to vector: effective vector weight = 0.8
- [ ] `calculate_combined_score` returns a float in `[0.0, 1.0]` for all valid input combinations
- [ ] Timezone-naive timestamps are treated as UTC (no `TypeError`)

## Dependencies

- TASK-US014-01 (`RetrievedChunk.vector_score`, `RetrievedChunk.keyword_score`, `RankingWeights`)
- TASK-US012-01 (`ChunkMetadata.timestamp: datetime` — recency signal source)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 90% for `src/retrieval/ranking/scorer.py`
- [ ] All three redistribution branches tested: both signals, vector-only, keyword-only
- [ ] `RECENCY_HALF_LIFE_DAYS` is the single source of truth — no inline `30` literals in scorer
- [ ] `mypy --strict` passes; no `ruff` lint errors
