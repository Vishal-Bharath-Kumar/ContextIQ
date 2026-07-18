"""Unit tests for CachedHybridSearchEngine — TASK-US013-03.

Coverage:
  - Cache hit: returns (chunks, True) without calling HybridSearchEngine.search().
  - Cache miss: calls HybridSearchEngine.search(), writes to cache, returns (chunks, False).
  - Empty result: HybridSearchEngine returns []; cache is NOT written; returns ([], False).
  - Singleton lifecycle: get_cached_hybrid_search_engine() raises before set, returns
    same instance after set; set resets the instance.
  - retrieval_node skips truncate_to_budget on cache-hit chunks.
  - retrieval_node applies truncate_to_budget on cache-miss chunks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.retrieval.engine.cached_hybrid_search as _module
from src.agents.schemas.execution_plan import RankingStrategy
from src.retrieval.engine.cached_hybrid_search import (
    CachedHybridSearchEngine,
    get_cached_hybrid_search_engine,
    set_cached_hybrid_search_engine,
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
    score: float = 0.9,
    idx: int = 0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=make_chunk_id(source_id, "src/main.py", idx),
        source_id=source_id,
        content=content,
        score=score,
        metadata=_METADATA,
        search_mode="rrf",
    )


def _make_chunks(n: int, source_id: str = "github") -> list[RetrievedChunk]:
    return [
        _make_chunk(source_id=source_id, content=f"chunk {i}", score=0.9 - i * 0.01, idx=i)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_engine() -> AsyncMock:
    engine = AsyncMock()
    engine.search = AsyncMock(return_value=_make_chunks(3))
    return engine


@pytest.fixture()
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)  # default: cache miss
    cache.set = AsyncMock(return_value=None)
    return cache


@pytest.fixture()
def mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed = MagicMock(return_value=[0.1, 0.2, 0.3])
    return embedder


@pytest.fixture()
def cached_engine(
    mock_engine: AsyncMock,
    mock_cache: AsyncMock,
    mock_embedder: MagicMock,
) -> CachedHybridSearchEngine:
    return CachedHybridSearchEngine(
        engine=mock_engine,
        cache=mock_cache,
        embedder=mock_embedder,
    )


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level _cached_engine singleton before and after each test."""
    original = _module._cached_engine
    _module._cached_engine = None
    yield
    _module._cached_engine = original


# ---------------------------------------------------------------------------
# CachedHybridSearchEngine.search — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_chunks_and_true(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    mock_engine: AsyncMock,
    mock_embedder: MagicMock,
) -> None:
    cached_chunks = _make_chunks(2)
    mock_cache.get = AsyncMock(return_value=cached_chunks)

    chunks, cache_hit = await cached_engine.search(
        query="What broke?",
        source_id="github",
        token_budget=500,
    )

    assert cache_hit is True
    assert chunks == cached_chunks


@pytest.mark.asyncio
async def test_cache_hit_does_not_call_underlying_engine(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    mock_engine: AsyncMock,
) -> None:
    mock_cache.get = AsyncMock(return_value=_make_chunks(2))

    await cached_engine.search(
        query="What broke?",
        source_id="github",
        token_budget=500,
    )

    mock_engine.search.assert_not_called()


# ---------------------------------------------------------------------------
# CachedHybridSearchEngine.search — cache miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_returns_chunks_and_false(
    cached_engine: CachedHybridSearchEngine,
    mock_engine: AsyncMock,
) -> None:
    chunks, cache_hit = await cached_engine.search(
        query="What broke?",
        source_id="github",
        token_budget=500,
    )

    assert cache_hit is False
    assert chunks == mock_engine.search.return_value


@pytest.mark.asyncio
async def test_cache_miss_calls_underlying_engine(
    cached_engine: CachedHybridSearchEngine,
    mock_engine: AsyncMock,
) -> None:
    await cached_engine.search(
        query="What broke?",
        source_id="github",
        token_budget=500,
        ranking_strategy=RankingStrategy.HYBRID,
    )

    mock_engine.search.assert_called_once_with(
        "What broke?", "github", RankingStrategy.HYBRID
    )


@pytest.mark.asyncio
async def test_cache_miss_writes_result_to_cache_exactly_once(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    mock_embedder: MagicMock,
    mock_engine: AsyncMock,
) -> None:
    chunks, _ = await cached_engine.search(
        query="What broke?",
        source_id="github",
        token_budget=500,
    )

    mock_cache.set.assert_called_once()
    written_chunks = mock_cache.set.call_args[0][1]
    assert written_chunks == chunks


# ---------------------------------------------------------------------------
# CachedHybridSearchEngine.search — empty result policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_result_not_written_to_cache(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    mock_engine: AsyncMock,
) -> None:
    mock_engine.search = AsyncMock(return_value=[])

    chunks, cache_hit = await cached_engine.search(
        query="Nothing here",
        source_id="github",
        token_budget=500,
    )

    assert cache_hit is False
    assert chunks == []
    mock_cache.set.assert_not_called()


# ---------------------------------------------------------------------------
# Singleton lifecycle
# ---------------------------------------------------------------------------


def test_get_cached_hybrid_search_engine_raises_before_set() -> None:
    with pytest.raises(RuntimeError, match="CachedHybridSearchEngine has not been initialised"):
        get_cached_hybrid_search_engine()


def test_set_and_get_singleton_returns_same_instance(
    mock_engine: AsyncMock,
    mock_cache: AsyncMock,
    mock_embedder: MagicMock,
) -> None:
    instance = CachedHybridSearchEngine(
        engine=mock_engine,
        cache=mock_cache,
        embedder=mock_embedder,
    )
    set_cached_hybrid_search_engine(instance)
    assert get_cached_hybrid_search_engine() is instance


def test_set_singleton_replaces_previous_instance(
    mock_engine: AsyncMock,
    mock_cache: AsyncMock,
    mock_embedder: MagicMock,
) -> None:
    first = CachedHybridSearchEngine(
        engine=mock_engine, cache=mock_cache, embedder=mock_embedder
    )
    second = CachedHybridSearchEngine(
        engine=mock_engine, cache=mock_cache, embedder=mock_embedder
    )
    set_cached_hybrid_search_engine(first)
    set_cached_hybrid_search_engine(second)
    assert get_cached_hybrid_search_engine() is second


# ---------------------------------------------------------------------------
# retrieval_node integration — truncation behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieval_node_skips_truncation_on_cache_hit() -> None:
    """Cache-hit chunks must not be re-truncated (they were truncated at write time)."""
    from src.agents.nodes.retrieval import retrieval_node
    from src.agents.schemas.execution_plan import ExecutionPlan
    from src.agents.state import AgentState

    cached_chunks = _make_chunks(5)

    mock_cached_engine = AsyncMock(spec=CachedHybridSearchEngine)
    mock_cached_engine.search = AsyncMock(return_value=(cached_chunks, True))

    plan = ExecutionPlan(
        sources=["github"],
        token_budget_total=2000,
        token_budget_per_source={"github": 2000},
        ranking_strategy=RankingStrategy.HYBRID,
        cache_eligible=True,
    )
    state: AgentState = {
        "execution_plan": plan,
        "prompt": "test query",
        "request_id": "req-001",
    }

    with (
        patch(
            "src.agents.nodes.retrieval.get_cached_hybrid_search_engine",
            return_value=mock_cached_engine,
        ),
        patch(
            "src.agents.nodes.retrieval.truncate_to_budget"
        ) as mock_truncate,
    ):
        result = await retrieval_node(state)

    # truncate_to_budget must NOT have been called for a cache hit
    mock_truncate.assert_not_called()
    assert result["raw_context"] == cached_chunks


@pytest.mark.asyncio
async def test_retrieval_node_applies_truncation_on_cache_miss() -> None:
    """Cache-miss chunks must be truncated via truncate_to_budget."""
    from src.agents.nodes.retrieval import retrieval_node
    from src.agents.schemas.execution_plan import ExecutionPlan
    from src.agents.state import AgentState

    live_chunks = _make_chunks(5)
    truncated_contents = [c.content for c in live_chunks[:3]]

    mock_cached_engine = AsyncMock(spec=CachedHybridSearchEngine)
    mock_cached_engine.search = AsyncMock(return_value=(live_chunks, False))

    plan = ExecutionPlan(
        sources=["github"],
        token_budget_total=2000,
        token_budget_per_source={"github": 2000},
        ranking_strategy=RankingStrategy.HYBRID,
        cache_eligible=False,
    )
    state: AgentState = {
        "execution_plan": plan,
        "prompt": "test query",
        "request_id": "req-001",
    }

    with (
        patch(
            "src.agents.nodes.retrieval.get_cached_hybrid_search_engine",
            return_value=mock_cached_engine,
        ),
        patch(
            "src.agents.nodes.retrieval.truncate_to_budget",
            return_value=truncated_contents,
        ) as mock_truncate,
    ):
        result = await retrieval_node(state)

    mock_truncate.assert_called_once()
    # Only 3 chunks kept after truncation
    assert len(result["raw_context"]) == 3
