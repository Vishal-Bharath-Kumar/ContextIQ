"""Combined relevance scorer for the Context Retrieval Engine (TASK-US014-02).

Combines vector similarity, keyword match, and recency decay signals into a
single score using the configured ``RankingWeights``.  Missing signals are
handled by proportional weight redistribution so that SEMANTIC-only and
BM25-only retrieval paths are scored correctly.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from src.retrieval.ranking.weights import RankingWeights
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECENCY_HALF_LIFE_DAYS: float = 30.0  # score halves every 30 days


# ---------------------------------------------------------------------------
# Recency signal
# ---------------------------------------------------------------------------


def calculate_recency_score(timestamp: datetime) -> float:
    """Return a [0.0, 1.0] recency signal using exponential decay.

    Score = 1.0 for age = 0 days; ≈ 0.5 at 30 days; ≈ 0.25 at 60 days.
    Timezone-naive timestamps are treated as UTC.
    """
    now = datetime.now(UTC)
    ts_aware = (
        timestamp.replace(tzinfo=UTC)
        if timestamp.tzinfo is None
        else timestamp
    )
    age_days = max((now - ts_aware).total_seconds() / 86_400, 0.0)
    decay_rate = math.log(2) / RECENCY_HALF_LIFE_DAYS
    return math.exp(-decay_rate * age_days)


# ---------------------------------------------------------------------------
# Weight redistribution
# ---------------------------------------------------------------------------


def _redistribute_weights(
    weights: RankingWeights,
    has_vector: bool,
    has_keyword: bool,
) -> tuple[float, float, float]:
    """Return (effective_v, effective_k, effective_r) summing to 1.0.

    When a signal is absent its weight is folded into the available signal so
    that the overall sum remains 1.0.  The recency weight is never
    redistributed.
    """
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


# ---------------------------------------------------------------------------
# Combined scorer
# ---------------------------------------------------------------------------


def calculate_combined_score(chunk: RetrievedChunk, weights: RankingWeights) -> float:
    """Compute the weighted combined relevance score for a single chunk.

    Returns a float in approximately [0.0, 1.0].
    (May slightly exceed 1.0 due to RRF score range; callers should clamp if
    needed.)
    """
    has_vector = chunk.vector_score is not None
    has_keyword = chunk.keyword_score is not None
    eff_v, eff_k, eff_r = _redistribute_weights(weights, has_vector, has_keyword)

    vector_signal = (chunk.vector_score or 0.0) * eff_v
    keyword_signal = (chunk.keyword_score or 0.0) * eff_k

    # For pure-RRF chunks where both individual scores are None, use chunk.score
    # as base signal weighted by the redistributed vector effective weight.
    if not has_vector and not has_keyword:
        base_signal = chunk.score * eff_v
    else:
        base_signal = vector_signal + keyword_signal

    recency_signal = calculate_recency_score(chunk.metadata.timestamp) * eff_r
    return base_signal + recency_signal
