"""Unit tests for HybridSearchEngine — TASK-US012-05.

All tests run without live backends:
  - QdrantSearchClient and OpenSearchSearchClient are replaced with AsyncMock.
  - asyncio.gather parallel dispatch is verified via call_count assertions.

Coverage:
  - HYBRID strategy: both clients called concurrently via asyncio.gather.
  - SEMANTIC strategy: only Qdrant is called; OpenSearch is not called.
  - BM25 strategy: only OpenSearch is called; Qdrant is not called.
  - Top-K cap: result list contains at most ``top_k`` items.
  - Singleton lifecycle: get_hybrid_search_engine() raises before set, returns
    same instance after set.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

import src.retrieval.engine.hybrid_search as _module
from src.agents.schemas.execution_plan import RankingStrategy
from src.retrieval.engine.hybrid_search import (
    HybridSearchEngine,
    get_hybrid_search_engine,
    set_hybrid_search_engine,
)
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk, make_chunk_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_METADATA = ChunkMetadata(
    file_path="src/main.py",
    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
    author="dev",
    url=None,
    chunk_index=0,
)


def _make_chunk(
    source_id: str = "github",
    content: str = "sample chunk",
    score: float = 0.8,
    idx: int = 0,
    search_mode: str = "vector",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=make_chunk_id(source_id, "src/main.py", idx),
        source_id=source_id,
        content=content,
        score=score,
        metadata=_METADATA,
        search_mode=search_mode,  # type: ignore[arg-type]
    )


def _make_chunks(n: int, source_id: str = "github", search_mode: str = "vector") -> list[RetrievedChunk]:
    return [
        _make_chunk(source_id=source_id, content=f"chunk {i}", score=0.9 - i * 0.01, idx=i, search_mode=search_mode)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level _engine singleton before and after each test."""
    original = _module._engine
    _module._engine = None
    yield
    _module._engine = original


@pytest.fixture()
def mock_qdrant() -> AsyncMock:
    mock = AsyncMock()
    mock.search = AsyncMock(return_value=_make_chunks(5, search_mode="vector"))
    return mock


@pytest.fixture()
def mock_opensearch() -> AsyncMock:
    mock = AsyncMock()
    mock.search = AsyncMock(return_value=_make_chunks(5, search_mode="keyword"))
    return mock


@pytest.fixture()
def engine(mock_qdrant: AsyncMock, mock_opensearch: AsyncMock) -> HybridSearchEngine:
    return HybridSearchEngine(qdrant=mock_qdrant, opensearch=mock_opensearch, top_k=20)


# ---------------------------------------------------------------------------
# HYBRID strategy — parallel dispatch
# ---------------------------------------------------------------------------

class TestHybridStrategy:
    def test_both_clients_called(
        self, engine: HybridSearchEngine, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock
    ) -> None:
        asyncio.run(engine.search("fix bug", "github", RankingStrategy.HYBRID))
        mock_qdrant.search.assert_called_once_with("fix bug", "github", 20)
        mock_opensearch.search.assert_called_once_with("fix bug", "github", 20)

    def test_returns_merged_list(self, engine: HybridSearchEngine) -> None:
        result = asyncio.run(engine.search("fix bug", "github", RankingStrategy.HYBRID))
        assert isinstance(result, list)
        assert all(isinstance(c, RetrievedChunk) for c in result)

    def test_result_at_most_top_k(self, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock) -> None:
        large = _make_chunks(25, search_mode="vector")
        mock_qdrant.search = AsyncMock(return_value=large)
        mock_opensearch.search = AsyncMock(return_value=large)
        engine = HybridSearchEngine(qdrant=mock_qdrant, opensearch=mock_opensearch, top_k=10)
        result = asyncio.run(engine.search("query", "github", RankingStrategy.HYBRID))
        assert len(result) <= 10

    def test_gather_dispatches_concurrently(
        self, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock
    ) -> None:
        """Both coroutines are passed to asyncio.gather — neither awaits before the other."""
        engine = HybridSearchEngine(qdrant=mock_qdrant, opensearch=mock_opensearch, top_k=20)
        with patch("src.retrieval.engine.hybrid_search.asyncio.gather", wraps=asyncio.gather) as spy:
            asyncio.run(engine.search("query", "github", RankingStrategy.HYBRID))
        # asyncio.gather should have been called once with exactly two coroutines.
        spy.assert_called_once()
        assert len(spy.call_args.args) == 2


# ---------------------------------------------------------------------------
# SEMANTIC strategy — Qdrant only
# ---------------------------------------------------------------------------

class TestSemanticStrategy:
    def test_only_qdrant_called(
        self, engine: HybridSearchEngine, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock
    ) -> None:
        asyncio.run(engine.search("embed query", "github", RankingStrategy.SEMANTIC))
        mock_qdrant.search.assert_called_once()
        mock_opensearch.search.assert_not_called()

    def test_returns_qdrant_results(
        self, engine: HybridSearchEngine, mock_qdrant: AsyncMock
    ) -> None:
        expected = _make_chunks(3, search_mode="vector")
        mock_qdrant.search = AsyncMock(return_value=expected)
        result = asyncio.run(engine.search("q", "github", RankingStrategy.SEMANTIC))
        assert result == expected


# ---------------------------------------------------------------------------
# BM25 strategy — OpenSearch only
# ---------------------------------------------------------------------------

class TestBM25Strategy:
    def test_only_opensearch_called(
        self, engine: HybridSearchEngine, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock
    ) -> None:
        asyncio.run(engine.search("exact term", "github", RankingStrategy.BM25))
        mock_opensearch.search.assert_called_once()
        mock_qdrant.search.assert_not_called()

    def test_returns_opensearch_results(
        self, engine: HybridSearchEngine, mock_opensearch: AsyncMock
    ) -> None:
        expected = _make_chunks(3, search_mode="keyword")
        mock_opensearch.search = AsyncMock(return_value=expected)
        result = asyncio.run(engine.search("q", "github", RankingStrategy.BM25))
        assert result == expected


# ---------------------------------------------------------------------------
# Default strategy fallback
# ---------------------------------------------------------------------------

def test_default_strategy_is_hybrid(
    engine: HybridSearchEngine, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock
) -> None:
    asyncio.run(engine.search("q", "github"))
    mock_qdrant.search.assert_called_once()
    mock_opensearch.search.assert_called_once()


# ---------------------------------------------------------------------------
# Singleton lifecycle
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_raises_before_set(self) -> None:
        with pytest.raises(RuntimeError, match="HybridSearchEngine has not been initialised"):
            get_hybrid_search_engine()

    def test_set_then_get_returns_same_instance(
        self, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock
    ) -> None:
        instance = HybridSearchEngine(qdrant=mock_qdrant, opensearch=mock_opensearch)
        set_hybrid_search_engine(instance)
        assert get_hybrid_search_engine() is instance

    def test_set_twice_replaces_instance(
        self, mock_qdrant: AsyncMock, mock_opensearch: AsyncMock
    ) -> None:
        first = HybridSearchEngine(qdrant=mock_qdrant, opensearch=mock_opensearch)
        second = HybridSearchEngine(qdrant=mock_qdrant, opensearch=mock_opensearch)
        set_hybrid_search_engine(first)
        set_hybrid_search_engine(second)
        assert get_hybrid_search_engine() is second
