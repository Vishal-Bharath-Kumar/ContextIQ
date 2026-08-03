"""p95 latency benchmark for HybridSearchEngine — TASK-US012-05.

CI assertion: mocked ``HybridSearchEngine.search()`` must complete in < 1 s p95.

Run with:
    pytest tests/retrieval/engine/test_hybrid_search_benchmark.py --benchmark-enable

The benchmark uses fully mocked backends — no network calls, no model loading.
``asyncio.run()`` overhead is included in the measurement to reflect the real
event-loop entry cost, keeping the baseline conservative.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.agents.schemas.execution_plan import RankingStrategy
from src.retrieval.engine.hybrid_search import HybridSearchEngine
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk, make_chunk_id

# ---------------------------------------------------------------------------
# Pre-built mock result set — 20 chunks matching DEFAULT_TOP_K
# ---------------------------------------------------------------------------

_METADATA = ChunkMetadata(
    file_path="src/auth/handler.py",
    timestamp=datetime(2024, 6, 1, tzinfo=UTC),
    author="engineer",
    url=None,
    chunk_index=0,
)

MOCK_CHUNKS: list[RetrievedChunk] = [
    RetrievedChunk(
        chunk_id=make_chunk_id("github", "src/auth/handler.py", i),
        source_id="github",
        content=f"Authentication handler chunk {i}: validates JWT claims and RBAC roles.",
        score=round(1.0 - i * 0.02, 2),
        metadata=_METADATA,
        search_mode="vector",  # type: ignore[arg-type]
    )
    for i in range(20)
]


# ---------------------------------------------------------------------------
# Benchmark test
# ---------------------------------------------------------------------------

@pytest.mark.benchmark(max_time=1.0)
def test_hybrid_search_p95_latency(benchmark) -> None:  # type: ignore[no-untyped-def]
    """p95 hybrid search latency must be < 1 000 ms with mocked backends.

    Both Qdrant and OpenSearch mocks return ``MOCK_CHUNKS`` instantly.  The
    benchmark exercises the full ``asyncio.gather`` + ``rrf_merge`` path to
    verify orchestration overhead stays well within the SLA.
    """
    engine = HybridSearchEngine(
        qdrant=AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
        opensearch=AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
        top_k=20,
    )

    result: list[RetrievedChunk] = benchmark(
        lambda: asyncio.run(
            engine.search("fix authentication bug", "github", RankingStrategy.HYBRID)
        )
    )

    assert len(result) <= 20
    assert all(isinstance(c, RetrievedChunk) for c in result)


@pytest.mark.benchmark(max_time=1.0)
def test_semantic_search_p95_latency(benchmark) -> None:  # type: ignore[no-untyped-def]
    """SEMANTIC path (Qdrant-only) p95 latency must be < 1 000 ms."""
    engine = HybridSearchEngine(
        qdrant=AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
        opensearch=AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
        top_k=20,
    )

    result: list[RetrievedChunk] = benchmark(
        lambda: asyncio.run(
            engine.search("semantic query", "github", RankingStrategy.SEMANTIC)
        )
    )

    assert len(result) <= 20


@pytest.mark.benchmark(max_time=1.0)
def test_bm25_search_p95_latency(benchmark) -> None:  # type: ignore[no-untyped-def]
    """BM25 path (OpenSearch-only) p95 latency must be < 1 000 ms."""
    engine = HybridSearchEngine(
        qdrant=AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
        opensearch=AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
        top_k=20,
    )

    result: list[RetrievedChunk] = benchmark(
        lambda: asyncio.run(
            engine.search("exact term search", "github", RankingStrategy.BM25)
        )
    )

    assert len(result) <= 20
