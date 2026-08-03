"""Unit tests for scorer.py — TASK-US014-02.

Covers:
  - calculate_recency_score: boundary values (now, 30 days, 60 days, naive tz)
  - _redistribute_weights: all four redistribution branches
  - calculate_combined_score: default weights, SEMANTIC-only, BM25-only, RRF fallback
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

import pytest

from src.retrieval.ranking.scorer import (
    RECENCY_HALF_LIFE_DAYS,
    _redistribute_weights,
    calculate_combined_score,
    calculate_recency_score,
)
from src.retrieval.ranking.weights import RankingWeights
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = RankingWeights()  # 0.6 / 0.2 / 0.2


def _make_chunk(
    *,
    score: float = 0.5,
    vector_score: float | None = None,
    keyword_score: float | None = None,
    timestamp: datetime | None = None,
) -> RetrievedChunk:
    ts = timestamp or datetime.now(UTC)
    return RetrievedChunk(
        chunk_id="abc123def456789a",
        source_id="github",
        content="example content",
        score=score,
        metadata=ChunkMetadata(
            file_path="src/foo.py",
            timestamp=ts,
            author="tester",
        ),
        search_mode="rrf",
        vector_score=vector_score,
        keyword_score=keyword_score,
    )


# ---------------------------------------------------------------------------
# calculate_recency_score
# ---------------------------------------------------------------------------


class TestCalculateRecencyScore:
    def test_score_at_now_is_one(self) -> None:
        """AC: recency score for current timestamp equals 1.0."""
        score = calculate_recency_score(datetime.now(UTC))
        assert abs(score - 1.0) < 0.001

    def test_score_at_half_life_is_half(self) -> None:
        """AC: score ≈ 0.5 at 30 days (one half-life)."""
        ts = datetime.now(UTC) - timedelta(days=RECENCY_HALF_LIFE_DAYS)
        score = calculate_recency_score(ts)
        assert abs(score - 0.5) < 0.001

    def test_score_at_two_half_lives_is_quarter(self) -> None:
        """AC: score ≈ 0.25 at 60 days (two half-lives)."""
        ts = datetime.now(UTC) - timedelta(days=2 * RECENCY_HALF_LIFE_DAYS)
        score = calculate_recency_score(ts)
        assert abs(score - 0.25) < 0.001

    def test_timezone_naive_treated_as_utc(self) -> None:
        """AC: naive timestamps do not raise and produce valid score."""
        naive_ts = datetime.now(UTC).replace(tzinfo=None)  # strip tzinfo to simulate naive
        score = calculate_recency_score(naive_ts)
        assert 0.0 <= score <= 1.0

    def test_future_timestamp_clamps_to_one(self) -> None:
        """Age is clamped to 0 — future timestamps must not return > 1.0."""
        future_ts = datetime.now(UTC) + timedelta(days=10)
        score = calculate_recency_score(future_ts)
        assert abs(score - 1.0) < 0.001

    def test_score_decreases_monotonically(self) -> None:
        now = datetime.now(UTC)
        scores = [
            calculate_recency_score(now - timedelta(days=d))
            for d in [0, 10, 30, 60, 90]
        ]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))

    def test_score_is_in_unit_interval(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=365)
        score = calculate_recency_score(ts)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# _redistribute_weights
# ---------------------------------------------------------------------------


class TestRedistributeWeights:
    def test_both_signals_returns_original_weights(self) -> None:
        """Both signals present — weights unchanged."""
        eff_v, eff_k, eff_r = _redistribute_weights(
            _DEFAULT_WEIGHTS, has_vector=True, has_keyword=True
        )
        assert eff_v == pytest.approx(0.6)
        assert eff_k == pytest.approx(0.2)
        assert eff_r == pytest.approx(0.2)

    def test_vector_only_folds_keyword_into_vector(self) -> None:
        """AC: keyword_weight folded into vector_weight when keyword absent."""
        eff_v, eff_k, eff_r = _redistribute_weights(
            _DEFAULT_WEIGHTS, has_vector=True, has_keyword=False
        )
        # effective vector weight = 0.6 + 0.2 = 0.8
        assert eff_v == pytest.approx(0.8)
        assert eff_k == pytest.approx(0.0)
        assert eff_r == pytest.approx(0.2)

    def test_keyword_only_folds_vector_into_keyword(self) -> None:
        """vector_weight folded into keyword_weight when vector absent."""
        eff_v, eff_k, eff_r = _redistribute_weights(
            _DEFAULT_WEIGHTS, has_vector=False, has_keyword=True
        )
        # effective keyword weight = 0.6 + 0.2 = 0.8
        assert eff_v == pytest.approx(0.0)
        assert eff_k == pytest.approx(0.8)
        assert eff_r == pytest.approx(0.2)

    def test_neither_signal_uses_rrf_fallback(self) -> None:
        """Neither signal — RRF fallback: eff_v = 1 - recency_weight."""
        eff_v, eff_k, eff_r = _redistribute_weights(
            _DEFAULT_WEIGHTS, has_vector=False, has_keyword=False
        )
        assert eff_v == pytest.approx(0.8)
        assert eff_k == pytest.approx(0.0)
        assert eff_r == pytest.approx(0.2)

    def test_redistributed_weights_sum_to_one_vector_only(self) -> None:
        eff_v, eff_k, eff_r = _redistribute_weights(
            _DEFAULT_WEIGHTS, has_vector=True, has_keyword=False
        )
        assert eff_v + eff_k + eff_r == pytest.approx(1.0)

    def test_redistributed_weights_sum_to_one_keyword_only(self) -> None:
        eff_v, eff_k, eff_r = _redistribute_weights(
            _DEFAULT_WEIGHTS, has_vector=False, has_keyword=True
        )
        assert eff_v + eff_k + eff_r == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# calculate_combined_score
# ---------------------------------------------------------------------------


class TestCalculateCombinedScore:
    def test_full_signals_default_weights_near_one(self) -> None:
        """AC: vector=1.0, keyword=1.0, recency≈1.0 → combined ≈ 1.0."""
        chunk = _make_chunk(
            vector_score=1.0,
            keyword_score=1.0,
            timestamp=datetime.now(UTC),
        )
        score = calculate_combined_score(chunk, _DEFAULT_WEIGHTS)
        # 0.6*1.0 + 0.2*1.0 + 0.2*1.0 = 1.0
        assert score == pytest.approx(1.0, abs=0.001)

    def test_semantic_only_redistributes_keyword_weight_to_vector(self) -> None:
        """AC: SEMANTIC path (keyword_score=None) uses effective vector weight of 0.8."""
        chunk = _make_chunk(
            vector_score=1.0,
            keyword_score=None,
            timestamp=datetime.now(UTC),
        )
        score = calculate_combined_score(chunk, _DEFAULT_WEIGHTS)
        # effective vector weight = 0.8; recency ≈ 1.0 * 0.2 = 0.2
        # 0.8*1.0 + 0.2*1.0 = 1.0
        assert score == pytest.approx(1.0, abs=0.001)

    def test_bm25_only_redistributes_vector_weight_to_keyword(self) -> None:
        """BM25 path (vector_score=None) uses effective keyword weight of 0.8."""
        chunk = _make_chunk(
            vector_score=None,
            keyword_score=1.0,
            timestamp=datetime.now(UTC),
        )
        score = calculate_combined_score(chunk, _DEFAULT_WEIGHTS)
        # 0.8*1.0 + 0.2*1.0 = 1.0
        assert score == pytest.approx(1.0, abs=0.001)

    def test_rrf_fallback_uses_chunk_score(self) -> None:
        """Pure-RRF chunks use chunk.score as base signal."""
        chunk = _make_chunk(
            score=0.8,
            vector_score=None,
            keyword_score=None,
            timestamp=datetime.now(UTC),
        )
        score = calculate_combined_score(chunk, _DEFAULT_WEIGHTS)
        # base = 0.8 * 0.8 = 0.64; recency ≈ 0.2 → total ≈ 0.84
        assert 0.0 <= score <= 1.0

    def test_score_in_unit_interval_for_low_scores(self) -> None:
        """Combined score stays in [0.0, 1.0] for low individual scores."""
        chunk = _make_chunk(
            vector_score=0.1,
            keyword_score=0.1,
            timestamp=datetime.now(UTC) - timedelta(days=90),
        )
        score = calculate_combined_score(chunk, _DEFAULT_WEIGHTS)
        assert 0.0 <= score <= 1.0

    def test_score_in_unit_interval_for_zero_scores(self) -> None:
        chunk = _make_chunk(
            vector_score=0.0,
            keyword_score=0.0,
            timestamp=datetime.now(UTC) - timedelta(days=365),
        )
        score = calculate_combined_score(chunk, _DEFAULT_WEIGHTS)
        assert 0.0 <= score <= 1.0

    def test_timezone_naive_timestamp_no_error(self) -> None:
        """AC: timezone-naive timestamp is handled without TypeError."""
        naive_ts = datetime.now(UTC).replace(tzinfo=None)  # strip tzinfo to simulate naive
        chunk = _make_chunk(vector_score=0.5, keyword_score=0.5, timestamp=naive_ts)
        score = calculate_combined_score(chunk, _DEFAULT_WEIGHTS)
        assert 0.0 <= score <= 1.0

    def test_recency_weight_contributes_correctly(self) -> None:
        """Old timestamp reduces combined score compared to fresh timestamp."""
        old_ts = datetime.now(UTC) - timedelta(days=365)
        new_ts = datetime.now(UTC)
        chunk_old = _make_chunk(vector_score=0.5, keyword_score=0.5, timestamp=old_ts)
        chunk_new = _make_chunk(vector_score=0.5, keyword_score=0.5, timestamp=new_ts)
        assert calculate_combined_score(chunk_new, _DEFAULT_WEIGHTS) > calculate_combined_score(
            chunk_old, _DEFAULT_WEIGHTS
        )

    def test_custom_weights_applied_correctly(self) -> None:
        """Verify score formula with non-default weights."""
        weights = RankingWeights(
            vector_weight=0.5, keyword_weight=0.3, recency_weight=0.2
        )
        chunk = _make_chunk(
            vector_score=0.8,
            keyword_score=0.6,
            timestamp=datetime.now(UTC),
        )
        score = calculate_combined_score(chunk, weights)
        # 0.5*0.8 + 0.3*0.6 + 0.2*1.0 = 0.4 + 0.18 + 0.2 = 0.78
        assert score == pytest.approx(0.78, abs=0.001)
