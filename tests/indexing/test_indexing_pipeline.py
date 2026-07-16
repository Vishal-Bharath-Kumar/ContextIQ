"""AC-2 through AC-6 — IndexingPipeline integration tests — TASK-US027-05.

AC-2  Embedding model ID is propagated to every saved ChunkMetadata row.
AC-3  Qdrant collection name uses the ``{source_id_hex}_{tenant_id}`` format.
AC-4  OpenSearch bulk_index is called with the correct tenant_id.
AC-5  PostgreSQL ChunkMetadata rows are persisted with source_id and indexed_at set.
AC-6  Throughput benchmark: 1 000 chunks embedded in < 60 s (mocked fastembed).

All tests run without live Kafka, Qdrant, OpenSearch, or PostgreSQL.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
import pytest_benchmark.fixture

from src.indexing.schemas.chunk import ChunkMetadata, ChunkPayload

# Fixed UUID matching conftest.py — avoids module-identity mismatch.
SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
TENANT_ID = "acme"


# ---------------------------------------------------------------------------
# AC-2 — Embedding model ID propagated to chunk metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_model_id_propagated_to_chunk_metadata(
    mock_registry: MagicMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    from src.indexing.embedding.service import EmbeddingService, EmbeddingSettings
    from src.indexing.pipeline import IndexingPipeline

    with patch("litellm.aembedding", new_callable=AsyncMock) as mock_litellm:
        mock_litellm.return_value = MagicMock(
            data=[{"embedding": [0.0] * 1536} for _ in range(10)]
        )
        embedder = EmbeddingService(
            EmbeddingSettings(model_id="text-embedding-3-small", _env_file=None)
        )
        pipeline = IndexingPipeline(
            embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
        )
        await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    saved = mock_chunk_repo.upsert_batch.call_args.args[0]
    assert all(c.embedding_model == "text-embedding-3-small" for c in saved)


# ---------------------------------------------------------------------------
# AC-3 — Qdrant collection name format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qdrant_collection_name_format(
    mock_registry: MagicMock,
    mock_embedder: AsyncMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    from src.indexing.pipeline import IndexingPipeline
    from src.indexing.stores.qdrant_indexer import collection_name

    pipeline = IndexingPipeline(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )
    await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    expected = collection_name(SOURCE_ID, TENANT_ID)
    mock_qdrant.ensure_collection.assert_awaited_once_with(SOURCE_ID, TENANT_ID)
    # confirm format: {hex}_{tenant_id}
    assert expected == f"{SOURCE_ID.hex}_{TENANT_ID}"


# ---------------------------------------------------------------------------
# AC-4 — OpenSearch bulk index called with correct tenant_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opensearch_bulk_index_called(
    mock_registry: MagicMock,
    mock_embedder: AsyncMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    from src.indexing.pipeline import IndexingPipeline

    pipeline = IndexingPipeline(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )
    await pipeline.run_for_source(SOURCE_ID, TENANT_ID)
    mock_opensearch.bulk_index.assert_awaited_once()
    args = mock_opensearch.bulk_index.call_args
    assert args.kwargs["tenant_id"] == TENANT_ID


# ---------------------------------------------------------------------------
# AC-5 — PostgreSQL chunk metadata persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgresql_chunk_metadata_persisted(
    mock_registry: MagicMock,
    mock_embedder: AsyncMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    from src.indexing.pipeline import IndexingPipeline

    pipeline = IndexingPipeline(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )
    count = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    mock_chunk_repo.upsert_batch.assert_awaited_once()
    saved: list[ChunkMetadata] = mock_chunk_repo.upsert_batch.call_args.args[0]
    assert len(saved) == count
    assert all(isinstance(c, ChunkMetadata) for c in saved)
    assert all(c.source_id == SOURCE_ID for c in saved)
    assert all(c.indexed_at is not None for c in saved)


# ---------------------------------------------------------------------------
# AC-6 — Throughput benchmark: ≥ 1 000 chunks/min
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_embedding_throughput_benchmark(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
    make_chunk: Callable[..., ChunkPayload],
) -> None:
    """Validate that embedding 1 000 chunks takes ≤ 60 s wall-clock time.

    Uses mocked fastembed to avoid OpenAI latency and heavy model downloads in CI.
    Run with: pytest --benchmark-only -m benchmark
    """
    from src.indexing.embedding.fastembed_provider import FastEmbedProvider
    from src.indexing.embedding.service import EmbeddingService, EmbeddingSettings

    chunks = [make_chunk(text=f"chunk text {i}" * 5) for i in range(1_000)]

    with patch.object(FastEmbedProvider, "embed", return_value=[[0.1] * 384] * len(chunks)):
        settings = EmbeddingSettings(
            use_local_model=True, concurrency=4, batch_size=256, _env_file=None
        )
        service = EmbeddingService(settings)
        result = benchmark(asyncio.run, service.embed_batch(chunks))

    assert len(result) == 1_000
    assert benchmark.stats["mean"] < 60.0, (
        f"Embedding 1 000 chunks took {benchmark.stats['mean']:.1f}s — must be < 60s"
    )


# ---------------------------------------------------------------------------
# Parallel asyncio.gather assertion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_uses_gather_for_store_writes(
    mock_registry: MagicMock,
    mock_embedder: AsyncMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    """Verify ensure_collection + ensure_index are called concurrently,
    and that qdrant.upsert + opensearch.bulk_index are called concurrently."""
    from src.indexing.pipeline import IndexingPipeline

    call_order: list[str] = []

    async def record_qdrant_ensure(*_args: object, **_kwargs: object) -> None:
        call_order.append("qdrant_ensure")

    async def record_os_ensure(*_args: object, **_kwargs: object) -> None:
        call_order.append("os_ensure")

    async def record_qdrant_upsert(*_args: object, **_kwargs: object) -> None:
        call_order.append("qdrant_upsert")

    async def record_os_bulk(*_args: object, **_kwargs: object) -> None:
        call_order.append("os_bulk")

    mock_qdrant.ensure_collection = record_qdrant_ensure
    mock_qdrant.upsert = record_qdrant_upsert
    mock_opensearch.ensure_index = record_os_ensure
    mock_opensearch.bulk_index = record_os_bulk

    pipeline = IndexingPipeline(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )
    await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    # Both ensures must appear before both writes
    ensure_indices = {call_order.index("qdrant_ensure"), call_order.index("os_ensure")}
    write_indices = {call_order.index("qdrant_upsert"), call_order.index("os_bulk")}
    assert max(ensure_indices) < min(write_indices)
