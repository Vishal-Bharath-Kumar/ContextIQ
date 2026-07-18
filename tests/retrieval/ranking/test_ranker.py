"""Unit tests for ContextRanker — TASK-US014-04.

Covers:
  - empty input returns []
  - all chunks below threshold → [] (filtered out)
  - output is ordered descending by combined score
  - output total token count does not exceed token_budget (budget-exact truncation)
  - input chunks and list are not mutated
  - custom weights and threshold are honoured
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.retrieval.ranking.config import DEFAULT_RELEVANCE_THRESHOLD
from src.retrieval.ranking.ranker import ContextRanker
from src.retrieval.ranking.weights import RankingWeights
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)


def _make_chunk(
    *,
    chunk_id: str = "abc123def4567890",
    score: float = 0.5,
    content: str = "hello world",
    vector_score: float | None = 0.8,
    keyword_score: float | None = 0.6,
    days_ago: int = 0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id="github",
        content=content,
        score=score,
        metadata=ChunkMetadata(
            file_path=f"src/{chunk_id}.py",
            timestamp=_NOW - timedelta(days=days_ago),
            author="tester",
        ),
        search_mode="rrf",
        vector_score=vector_score,
        keyword_score=keyword_score,
    )


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_rank_empty_list_returns_empty(self) -> None:
        """AC: ContextRanker.rank([]) returns []."""
        ranker = ContextRanker()
        assert ranker.rank([], token_budget=8_000) == []


# ---------------------------------------------------------------------------
# Threshold filtering
# ---------------------------------------------------------------------------


class TestThresholdFiltering:
    def test_all_below_threshold_returns_empty(self) -> None:
        """AC: all chunks below DEFAULT_RELEVANCE_THRESHOLD → []."""
        # Use vector_score=0.0, keyword_score=0.0, days_ago=365 to force a very
        # low combined score regardless of recency
        chunks = [
            _make_chunk(
                chunk_id=f"chunk{i:04d}00000000",
                vector_score=0.0,
                keyword_score=0.0,
                days_ago=365,
            )
            for i in range(5)
        ]
        ranker = ContextRanker(threshold=DEFAULT_RELEVANCE_THRESHOLD)
        result = ranker.rank(chunks, token_budget=8_000)
        assert result == []

    def test_high_threshold_excludes_moderate_chunks(self) -> None:
        """AC: chunks below a custom threshold of 0.9 are excluded."""
        chunks = [
            _make_chunk(chunk_id="aaaa000000000001", vector_score=0.5, keyword_score=0.3, days_ago=0),
            _make_chunk(chunk_id="aaaa000000000002", vector_score=0.9, keyword_score=0.9, days_ago=0),
        ]
        ranker = ContextRanker(threshold=0.9)
        result = ranker.rank(chunks, token_budget=8_000)
        assert all(c.score >= 0.9 for c in result)


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder:
    def test_output_descending_by_score(self) -> None:
        """AC: output is ordered descending by score (highest first)."""
        chunks = [
            _make_chunk(chunk_id=f"sort{i:012d}", vector_score=v, keyword_score=0.5, days_ago=0)
            for i, v in enumerate([0.6, 0.9, 0.7, 0.8])
        ]
        ranker = ContextRanker()
        result = ranker.rank(chunks, token_budget=8_000)
        scores = [c.score for c in result]
        assert scores == sorted(scores, reverse=True)

    def test_first_chunk_has_highest_score(self) -> None:
        """AC: first element in output has the maximum score."""
        chunks = [
            _make_chunk(chunk_id=f"best{i:012d}", vector_score=v, keyword_score=0.5, days_ago=0)
            for i, v in enumerate([0.7, 0.95, 0.8])
        ]
        ranker = ContextRanker()
        result = ranker.rank(chunks, token_budget=8_000)
        assert result[0].score == max(c.score for c in result)


# ---------------------------------------------------------------------------
# Token budget truncation
# ---------------------------------------------------------------------------


class TestTokenBudgetTruncation:
    def test_output_fits_within_token_budget(self) -> None:
        """AC: sum of token counts of output chunks does not exceed token_budget."""
        from src.retrieval.ranking.filters import count_tokens

        # ~20 tokens per chunk
        chunks = [
            _make_chunk(
                chunk_id=f"tok{i:013d}",
                content="def foo(): return 42  # some code here",
                vector_score=0.8,
                keyword_score=0.7,
                days_ago=i % 30,
            )
            for i in range(20)
        ]
        budget = 50  # only a few chunks will fit
        ranker = ContextRanker()
        result = ranker.rank(chunks, token_budget=budget)
        total = sum(count_tokens(c.content) for c in result)
        assert total <= budget

    def test_budget_exact_truncation(self) -> None:
        """AC: truncation stops at exact budget boundary (no partial chunks)."""
        from src.retrieval.ranking.filters import count_tokens

        content = "token " * 10  # fixed-size chunks
        tokens_per_chunk = count_tokens(content)
        budget = tokens_per_chunk * 3

        chunks = [
            _make_chunk(
                chunk_id=f"exact{i:011d}",
                content=content,
                vector_score=0.9,
                keyword_score=0.8,
                days_ago=0,
            )
            for i in range(10)
        ]
        ranker = ContextRanker()
        result = ranker.rank(chunks, token_budget=budget)
        total = sum(count_tokens(c.content) for c in result)
        assert total <= budget
        assert len(result) == 3

    def test_single_oversized_chunk_returns_empty(self) -> None:
        """AC: a single chunk exceeding budget yields []."""
        huge_content = "word " * 2_000  # >> any reasonable budget
        chunks = [
            _make_chunk(chunk_id="huge000000000001", content=huge_content, vector_score=0.9, keyword_score=0.9)
        ]
        ranker = ContextRanker()
        result = ranker.rank(chunks, token_budget=10)
        assert result == []


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_input_list_not_mutated(self) -> None:
        """AC: ContextRanker does not mutate the input list."""
        chunks = [
            _make_chunk(chunk_id=f"mut{i:013d}", vector_score=0.8, keyword_score=0.7, days_ago=0)
            for i in range(5)
        ]
        original_ids = [id(c) for c in chunks]
        original_scores = [c.score for c in chunks]
        ranker = ContextRanker()
        ranker.rank(chunks, token_budget=8_000)
        assert [id(c) for c in chunks] == original_ids
        assert [c.score for c in chunks] == original_scores

    def test_input_chunk_scores_unchanged(self) -> None:
        """AC: original RetrievedChunk instances keep their original scores."""
        chunk = _make_chunk(score=0.01639, vector_score=0.8, keyword_score=0.6, days_ago=0)
        original_score = chunk.score
        ranker = ContextRanker()
        ranker.rank([chunk], token_budget=8_000)
        assert chunk.score == original_score


# ---------------------------------------------------------------------------
# Custom weights and threshold
# ---------------------------------------------------------------------------


class TestCustomWeightsAndThreshold:
    def test_custom_weights_applied(self) -> None:
        """AC: custom RankingWeights are passed through to calculate_combined_score."""
        # Keyword-heavy weights: keyword matters most
        weights = RankingWeights(vector_weight=0.2, keyword_weight=0.6, recency_weight=0.2)
        chunks = [
            _make_chunk(chunk_id="cust000000000001", vector_score=0.5, keyword_score=0.9, days_ago=0),
        ]
        ranker = ContextRanker(weights=weights)
        result = ranker.rank(chunks, token_budget=8_000)
        # keyword_score=0.9 * 0.6 = 0.54; total well above 0.5 threshold
        assert len(result) == 1
        assert result[0].score > DEFAULT_RELEVANCE_THRESHOLD

    def test_custom_threshold_zero_keeps_all(self) -> None:
        """AC: threshold=0.0 keeps all chunks regardless of score."""
        chunks = [
            _make_chunk(
                chunk_id=f"zero{i:012d}",
                vector_score=0.0,
                keyword_score=0.0,
                days_ago=365,
            )
            for i in range(3)
        ]
        ranker = ContextRanker(threshold=0.0)
        result = ranker.rank(chunks, token_budget=8_000)
        assert len(result) == 3
