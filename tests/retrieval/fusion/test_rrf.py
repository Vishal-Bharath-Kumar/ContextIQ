"""Unit tests for ReciprocRankFusion and rrf_merge (TASK-US012-04)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from src.retrieval.fusion.rrf import (
    DEFAULT_K,
    DEFAULT_TOP_K,
    ReciprocRankFusion,
    rrf_merge,
)
from src.retrieval.schemas.retrieved_chunk import (
    ChunkMetadata,
    RetrievedChunk,
    make_chunk_id,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_META = ChunkMetadata(
    file_path="docs/test.md",
    timestamp=datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC),
    author="tester",
)


def _make_chunk(
    idx: int,
    *,
    source_id: str = "src",
    score: float = 0.5,
    search_mode: str = "vector",
) -> RetrievedChunk:
    """Return a deterministic RetrievedChunk keyed by *idx*."""
    cid = make_chunk_id(source_id, "docs/test.md", idx)
    return RetrievedChunk(
        chunk_id=cid,
        source_id=source_id,
        content=f"Chunk content {idx}.",
        score=score,
        metadata=_META,
        search_mode=search_mode,  # type: ignore[arg-type]
    )


def _make_list(n: int, *, source_id: str = "src", base_score: float = 0.9) -> list[RetrievedChunk]:
    """Return a ranked list of *n* distinct chunks in descending score order."""
    return [
        _make_chunk(i, source_id=source_id, score=round(base_score - i * 0.01, 4))
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_default_k(self) -> None:
        assert DEFAULT_K == 60

    def test_default_top_k(self) -> None:
        assert DEFAULT_TOP_K == 20


# ---------------------------------------------------------------------------
# RRF score arithmetic
# ---------------------------------------------------------------------------


class TestRrfScoreArithmetic:
    def test_rank1_score_equals_1_over_61(self) -> None:
        """AC: RRF score of chunk ranked #1 with k=60 equals 1/61."""
        chunk = _make_chunk(0, score=0.9)
        result = rrf_merge([chunk], [], k=60, top_k=1)
        assert len(result) == 1
        assert math.isclose(result[0].score, 1.0 / 61, rel_tol=1e-9)

    def test_dual_list_rank1_higher_than_single_list_rank1(self) -> None:
        """AC: chunk ranked #1 in both lists scores higher than chunk ranked #1 in only one."""
        shared = _make_chunk(0, score=0.9)
        only_vector = _make_chunk(1, score=0.8)

        vector_results = [shared, only_vector]
        keyword_results = [shared]

        result = rrf_merge(vector_results, keyword_results, k=60, top_k=10)

        shared_score = next(r.score for r in result if r.chunk_id == shared.chunk_id)
        only_vector_score = next(r.score for r in result if r.chunk_id == only_vector.chunk_id)

        assert shared_score > only_vector_score

    def test_dual_list_rank1_score_equals_2_over_61(self) -> None:
        """Chunk at rank 1 in both lists accumulates 1/61 + 1/61 = 2/61."""
        chunk = _make_chunk(0, score=0.9)
        result = rrf_merge([chunk], [chunk], k=60, top_k=1)
        assert math.isclose(result[0].score, 2.0 / 61, rel_tol=1e-9)

    def test_lower_rank_produces_lower_score(self) -> None:
        """Rank 2 score (1/62) must be less than rank 1 score (1/61)."""
        c1 = _make_chunk(0, score=0.9)
        c2 = _make_chunk(1, score=0.8)
        result = rrf_merge([c1, c2], [], k=60, top_k=2)
        scores = [r.score for r in result]
        assert scores[0] > scores[1]
        assert math.isclose(scores[1], 1.0 / 62, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Empty and degenerate inputs
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    def test_both_lists_empty_returns_empty(self) -> None:
        """AC: rrf_merge([], []) returns []."""
        assert rrf_merge([], []) == []

    def test_vector_empty_keyword_non_empty(self) -> None:
        keyword = _make_list(3, source_id="os")
        result = rrf_merge([], keyword)
        assert len(result) == 3

    def test_keyword_empty_vector_non_empty(self) -> None:
        vector = _make_list(3)
        result = rrf_merge(vector, [])
        assert len(result) == 3

    def test_single_chunk_single_list(self) -> None:
        chunk = _make_chunk(0, score=0.7)
        result = rrf_merge([chunk], [])
        assert len(result) == 1
        assert result[0].chunk_id == chunk.chunk_id


# ---------------------------------------------------------------------------
# Top-K truncation
# ---------------------------------------------------------------------------


class TestTopKTruncation:
    def test_top_k_5_returns_exactly_5(self) -> None:
        """AC: top_k=5 returns exactly 5 chunks when both lists have ≥5 distinct chunks."""
        vector = _make_list(10)
        keyword = _make_list(10, source_id="os", base_score=0.88)
        result = rrf_merge(vector, keyword, top_k=5)
        assert len(result) == 5

    def test_default_top_k_applied(self) -> None:
        vector = _make_list(30)
        keyword = _make_list(30, source_id="os", base_score=0.88)
        result = rrf_merge(vector, keyword)
        assert len(result) == DEFAULT_TOP_K

    def test_top_k_larger_than_pool_returns_all(self) -> None:
        vector = _make_list(3)
        keyword = _make_list(3, source_id="os", base_score=0.88)
        # 6 distinct chunks total
        result = rrf_merge(vector, keyword, top_k=100)
        assert len(result) == 6

    def test_results_ordered_descending_by_score(self) -> None:
        vector = _make_list(10)
        keyword = _make_list(10, source_id="os", base_score=0.88)
        result = rrf_merge(vector, keyword, top_k=10)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_chunk_in_both_lists_appears_once(self) -> None:
        """AC: chunks present in both lists are deduplicated — one entry per chunk_id."""
        shared = _make_chunk(0, score=0.9)
        vector = [shared, _make_chunk(1, score=0.8)]
        keyword = [shared, _make_chunk(2, source_id="os", score=0.75)]
        result = rrf_merge(vector, keyword, top_k=10)
        ids = [r.chunk_id for r in result]
        assert len(ids) == len(set(ids)), "Duplicate chunk_id in output"

    def test_best_chunk_payload_retained(self) -> None:
        """When a chunk appears in both lists, instance with higher score is kept for payload."""
        cid = make_chunk_id("src", "docs/test.md", 0)
        high_score_chunk = RetrievedChunk(
            chunk_id=cid,
            source_id="src",
            content="Vector content.",
            score=0.9,
            metadata=_META,
            search_mode="vector",
        )
        low_score_chunk = RetrievedChunk(
            chunk_id=cid,
            source_id="src",
            content="Keyword content.",
            score=0.6,
            metadata=_META,
            search_mode="keyword",
        )
        result = rrf_merge([high_score_chunk], [low_score_chunk], top_k=1)
        assert result[0].content == "Vector content."

    def test_fully_overlapping_lists_returns_same_count_as_unique_chunks(self) -> None:
        chunks = _make_list(5)
        result = rrf_merge(chunks, chunks, top_k=10)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# search_mode marking
# ---------------------------------------------------------------------------


class TestSearchModeMarking:
    def test_all_output_chunks_have_rrf_search_mode(self) -> None:
        """AC: search_mode is 'rrf' for all chunks in the merged output."""
        vector = _make_list(5)
        keyword = _make_list(5, source_id="os", base_score=0.88)
        result = rrf_merge(vector, keyword, top_k=10)
        assert all(r.search_mode == "rrf" for r in result)

    def test_single_list_output_chunks_have_rrf_search_mode(self) -> None:
        chunks = _make_list(3)
        result = rrf_merge(chunks, [])
        assert all(r.search_mode == "rrf" for r in result)


# ---------------------------------------------------------------------------
# Multi-list merge via ReciprocRankFusion.merge directly
# ---------------------------------------------------------------------------


class TestMultiListMerge:
    def test_three_lists_merged(self) -> None:
        a = _make_list(5)
        b = _make_list(5, source_id="os", base_score=0.88)
        c = _make_list(5, source_id="neo4j", base_score=0.77)
        fusion = ReciprocRankFusion(k=60, top_k=15)
        result = fusion.merge(a, b, c)
        assert len(result) == 15

    def test_chunk_in_all_three_lists_outscores_chunk_in_one(self) -> None:
        shared = _make_chunk(99, score=0.5)
        unique = _make_chunk(100, score=0.9)
        a = [shared, unique]
        b = [shared]
        c = [shared]
        fusion = ReciprocRankFusion(k=60, top_k=10)
        result = fusion.merge(a, b, c)
        shared_score = next(r.score for r in result if r.chunk_id == shared.chunk_id)
        unique_score = next(r.score for r in result if r.chunk_id == unique.chunk_id)
        # shared appears in 3 lists (rank 1 each for b and c, rank 1 for a)
        # => 3/61; unique appears only in a at rank 2 => 1/62
        assert shared_score > unique_score

    def test_custom_k_affects_scores(self) -> None:
        chunk = _make_chunk(0, score=0.9)
        result_k60 = ReciprocRankFusion(k=60, top_k=1).merge([chunk])
        result_k10 = ReciprocRankFusion(k=10, top_k=1).merge([chunk])
        # k=10 → 1/11 > k=60 → 1/61
        assert result_k10[0].score > result_k60[0].score
