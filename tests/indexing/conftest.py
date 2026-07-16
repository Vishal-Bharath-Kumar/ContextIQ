"""Shared fixtures for the indexing test suite — TASK-US027-05.

All tests run without live Kafka, Qdrant, OpenSearch, or PostgreSQL.
"""
from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.indexing.schemas.chunk import ChunkPayload

# Fixed UUID so this constant is identical regardless of how many times the
# module is imported (pytest loads conftest.py separately from the test file).
SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
TENANT_ID = "acme"


@pytest.fixture
def make_chunk() -> Callable[..., ChunkPayload]:
    def _make(text: str = "hello world", token_count: int = 10) -> ChunkPayload:
        return ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id=TENANT_ID,
            document_id=f"github:org/repo:{uuid4().hex[:8]}",
            text=text,
            token_count=token_count,
        )
    return _make


@pytest.fixture
def mock_qdrant() -> AsyncMock:
    q = AsyncMock()
    q.ensure_collection = AsyncMock()
    q.upsert = AsyncMock()
    q.delete_by_document = AsyncMock()
    return q


@pytest.fixture
def mock_opensearch() -> AsyncMock:
    o = AsyncMock()
    o.ensure_index = AsyncMock()
    o.bulk_index = AsyncMock()
    o.delete_by_document = AsyncMock()
    return o


@pytest.fixture
def mock_chunk_repo() -> AsyncMock:
    r = AsyncMock()
    r.upsert_batch = AsyncMock()
    r.list_by_document = AsyncMock(return_value=[])
    r.delete_by_document = AsyncMock(return_value=0)
    return r


@pytest.fixture
def mock_embedder(make_chunk: Callable[..., ChunkPayload]) -> AsyncMock:  # noqa: ARG001
    from src.indexing.schemas.chunk import IndexedChunk

    async def _embed(chunks: list[ChunkPayload]) -> list[IndexedChunk]:
        return [
            IndexedChunk(payload=c, vector=[0.1] * 1536, model_id="text-embedding-3-small")
            for c in chunks
        ]

    e = AsyncMock()
    e.embed_batch = AsyncMock(side_effect=_embed)
    return e


@pytest.fixture
def mock_connector(make_chunk: Callable[..., ChunkPayload]) -> AsyncMock:
    c = AsyncMock()
    c.get_chunks = AsyncMock(return_value=[make_chunk() for _ in range(10)])
    return c


@pytest.fixture
def mock_registry(mock_connector: AsyncMock) -> MagicMock:
    r = MagicMock()
    r.get = MagicMock(return_value=mock_connector)
    return r
