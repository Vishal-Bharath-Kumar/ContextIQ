"""Unit tests for filters.py — TASK-US014-03.

Covers:
  - filter_below_threshold: threshold boundary (equal, below, above), empty input,
    threshold=0.0 (keep all), threshold=1.0 (only perfect scores)
  - truncate_to_token_budget: exact-fit, one-over-budget, single oversized chunk,
    empty input, partial list kept when mid-list chunk overflows
  - DEFAULT_RELEVANCE_THRESHOLD value
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.retrieval.ranking.config import DEFAULT_RELEVANCE_THRESHOLD
from src.retrieval.ranking.filters import (
    count_tokens,
    filter_below_threshold,
    truncate_to_token_budget,
)
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(*, score: float = 0.5, content: str = "hello world") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="abc123def456789a",
        source_id="github",
        content=content,
        score=score,
        metadata=ChunkMetadata(
            file_path="src/foo.py",
            timestamp=datetime.now(UTC),
            author="tester",
        ),
        search_mode="rrf",
    )


# ---------------------------------------------------------------------------
# DEFAULT_RELEVANCE_THRESHOLD
# ---------------------------------------------------------------------------


class TestDefaultRelevanceThreshold:
    def test_value_is_0_5(self) -> None:
        """AC: DEFAULT_RELEVANCE_THRESHOLD equals 0.5."""
        assert DEFAULT_RELEVANCE_THRESHOLD == 0.5


# ---------------------------------------------------------------------------
# filter_below_threshold
# ---------------------------------------------------------------------------


class TestFilterBelowThreshold:
    def test_keeps_chunks_at_and_above_threshold(self) -> None:
        """AC: chunks with score >= threshold are retained."""
        chunks = [
            _make_chunk(score=0.4),
            _make_chunk(score=0.5),
            _make_chunk(score=0.6),
        ]
        result = filter_below_threshold(chunks, threshold=0.5)
        assert len(result) == 2
        assert all(c.score >= 0.5 for c in result)

    def test_excludes_chunk_strictly_below_threshold(self) -> None:
        """AC: chunk with score strictly below threshold is excluded."""
        chunks = [_make_chunk(score=0.49), _make_chunk(score=0.5)]
        result = filter_below_threshold(chunks, threshold=0.5)
        assert len(result) == 1
        assert result[0].score == 0.5

    def test_equal_to_threshold_is_kept(self) -> None:
        """AC: chunk with score exactly equal to threshold is kept (inclusive)."""
        chunk = _make_chunk(score=0.5)
        result = filter_below_threshold([chunk], threshold=0.5)
        assert result == [chunk]

    def test_empty_input_returns_empty(self) -> None:
        """AC: empty chunk list returns empty list."""
        assert filter_below_threshold([], threshold=0.5) == []

    def test_threshold_zero_returns_all(self) -> None:
        """AC: threshold=0.0 keeps every chunk regardless of score."""
        chunks = [_make_chunk(score=0.0), _make_chunk(score=0.3), _make_chunk(score=1.0)]
        result = filter_below_threshold(chunks, threshold=0.0)
        assert len(result) == 3

    def test_threshold_one_keeps_only_perfect_score(self) -> None:
        """AC: threshold=1.0 keeps only chunks with score==1.0."""
        chunks = [_make_chunk(score=0.99), _make_chunk(score=1.0)]
        result = filter_below_threshold(chunks, threshold=1.0)
        assert len(result) == 1
        assert result[0].score == 1.0

    def test_default_threshold_is_0_5(self) -> None:
        """AC: default threshold is DEFAULT_RELEVANCE_THRESHOLD (0.5)."""
        chunks = [_make_chunk(score=0.49), _make_chunk(score=0.5), _make_chunk(score=0.51)]
        result = filter_below_threshold(chunks)
        assert len(result) == 2

    def test_all_below_threshold_returns_empty(self) -> None:
        """AC: all chunks below threshold → empty list."""
        chunks = [_make_chunk(score=0.1), _make_chunk(score=0.2)]
        result = filter_below_threshold(chunks, threshold=0.9)
        assert result == []

    def test_order_is_preserved(self) -> None:
        """AC: original list order is preserved in the filtered result."""
        chunks = [_make_chunk(score=0.9), _make_chunk(score=0.7), _make_chunk(score=0.6)]
        result = filter_below_threshold(chunks, threshold=0.5)
        assert [c.score for c in result] == [0.9, 0.7, 0.6]


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_empty_string(self) -> None:
        """count_tokens on empty string returns 0."""
        assert count_tokens("") == 0

    def test_known_token_count(self) -> None:
        """count_tokens returns a positive integer for non-empty text."""
        assert count_tokens("hello world") > 0

    def test_longer_text_has_more_tokens(self) -> None:
        """Longer content produces more tokens than shorter content."""
        short = count_tokens("hi")
        long = count_tokens("hi " * 100)
        assert long > short


# ---------------------------------------------------------------------------
# truncate_to_token_budget
# ---------------------------------------------------------------------------


class TestTruncateToTokenBudget:
    def _chunk_with_tokens(self, n_tokens: int, score: float = 0.9) -> RetrievedChunk:
        """Create a chunk whose content encodes to exactly *n_tokens* tokens.

        Uses a single repeated word; actual token count is verified by count_tokens.
        We build the content iteratively to guarantee the exact token count.
        """
        # "token" encodes to 1 token in cl100k_base
        content = "token " * n_tokens
        # Trim to ensure we have exactly n_tokens (strip trailing space)
        content = content.rstrip()
        actual = count_tokens(content)
        # Adjust if needed (handles edge cases in encoding)
        if actual > n_tokens:
            # Fall back: use space-separated single chars (each 1 token)
            content = " ".join(["a"] * n_tokens)
        return _make_chunk(score=score, content=content)

    def test_empty_input_returns_empty(self) -> None:
        """AC: empty chunk list returns empty list."""
        assert truncate_to_token_budget([], budget=100) == []

    def test_single_oversized_chunk_returns_empty(self) -> None:
        """AC: a single chunk exceeding the budget → empty list (no RuntimeError)."""
        chunk = _make_chunk(content="word " * 200)
        budget = 1  # far less than the chunk's token count
        result = truncate_to_token_budget([chunk], budget=budget)
        assert result == []

    def test_exact_budget_fit_keeps_chunk(self) -> None:
        """AC: chunk that fits exactly within budget is kept."""
        content = "hello"
        tokens = count_tokens(content)
        chunk = _make_chunk(content=content)
        result = truncate_to_token_budget([chunk], budget=tokens)
        assert result == [chunk]

    def test_one_token_over_budget_excludes_chunk(self) -> None:
        """AC: chunk that is 1 token over budget is excluded."""
        content = "hello"
        tokens = count_tokens(content)
        chunk = _make_chunk(content=content)
        result = truncate_to_token_budget([chunk], budget=tokens - 1)
        assert result == []

    def test_keeps_prefix_when_mid_chunk_overflows(self) -> None:
        """AC: stops at first chunk that would exceed budget; earlier chunks are kept."""
        small = _make_chunk(content="hi", score=0.9)
        large = _make_chunk(content="word " * 500, score=0.8)
        small_tokens = count_tokens("hi")
        result = truncate_to_token_budget([small, large], budget=small_tokens)
        assert result == [small]

    def test_all_chunks_fit(self) -> None:
        """AC: all chunks are kept when combined tokens ≤ budget."""
        chunks = [_make_chunk(content="hi", score=0.9) for _ in range(3)]
        total = sum(count_tokens(c.content) for c in chunks)
        result = truncate_to_token_budget(chunks, budget=total)
        assert result == chunks

    def test_only_complete_chunks_included(self) -> None:
        """AC: no partial-content chunks appear in the result."""
        chunk_a = _make_chunk(content="alpha beta gamma", score=0.9)
        chunk_b = _make_chunk(content="delta epsilon zeta", score=0.8)
        tokens_a = count_tokens(chunk_a.content)
        # budget just enough for chunk_a but not chunk_b
        result = truncate_to_token_budget([chunk_a, chunk_b], budget=tokens_a)
        assert len(result) == 1
        assert result[0].content == chunk_a.content

    def test_zero_budget_returns_empty(self) -> None:
        """AC: budget=0 means no chunk can fit → empty list."""
        chunk = _make_chunk(content="any text")
        result = truncate_to_token_budget([chunk], budget=0)
        assert result == []

    def test_large_budget_keeps_all(self) -> None:
        """AC: very large budget keeps the entire list."""
        chunks = [_make_chunk(content=f"content chunk {i}") for i in range(5)]
        result = truncate_to_token_budget(chunks, budget=100_000)
        assert result == chunks
