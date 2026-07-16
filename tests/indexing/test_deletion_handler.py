"""AC-7 — Stale embedding deletion tests — TASK-US027-05.

Verifies that DeletionHandler correctly orchestrates removal of stale
chunk data from all three stores (Qdrant, OpenSearch, PostgreSQL), and that
it performs no external calls when no chunks exist for the document.

All tests run without live Kafka, Qdrant, OpenSearch, or PostgreSQL.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.indexing.models.chunk import ChunkRecord
from src.indexing.stores.deletion_handler import DeletionHandler

# Fixed UUID matching conftest.py — avoids module-identity mismatch.
SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
TENANT_ID = "acme"


@pytest.mark.asyncio
async def test_deletion_handler_calls_all_three_stores(
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    doc_id = "confluence:SPACE:12345"
    chunk_records = [MagicMock(spec=ChunkRecord, chunk_id=uuid4()) for _ in range(3)]
    mock_chunk_repo.list_by_document = AsyncMock(return_value=chunk_records)

    handler = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    await handler.handle(doc_id, SOURCE_ID, TENANT_ID)

    mock_qdrant.delete_by_document.assert_awaited_once()
    mock_opensearch.delete_by_document.assert_awaited_once_with(doc_id, TENANT_ID)
    mock_chunk_repo.delete_by_document.assert_awaited_once_with(doc_id)


@pytest.mark.asyncio
async def test_deletion_handler_no_qdrant_call_when_no_chunks(
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    mock_chunk_repo.list_by_document = AsyncMock(return_value=[])

    handler = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    await handler.handle("doc:none", SOURCE_ID, TENANT_ID)
    mock_qdrant.delete_by_document.assert_not_awaited()

