"""AC-1 — Kafka consumer routing tests — TASK-US027-05.

Verifies that IndexingConsumer correctly dispatches:
  - ``knowledge_source_synced``  → IndexingPipeline.run_for_source
  - ``knowledge_document_deleted`` → DeletionHandler.handle
  - unknown event types          → silently skipped (poison-pill safety)

All tests run without a live Kafka broker.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.indexing.consumer import IndexingConsumer, IndexingConsumerSettings
from src.indexing.pipeline import IndexingPipeline
from src.indexing.stores.deletion_handler import DeletionHandler

# Fixed UUID matching conftest.py — avoids module-identity mismatch.
SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
TENANT_ID = "acme"

_SETTINGS = IndexingConsumerSettings(_env_file=None)


def _make_consumer(
    mock_embedder: AsyncMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
    mock_registry: MagicMock,
) -> IndexingConsumer:
    pipeline = IndexingPipeline(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )
    deletion = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    return IndexingConsumer(pipeline=pipeline, deletion_handler=deletion, settings=_SETTINGS)


@pytest.mark.asyncio
async def test_consumer_routes_synced_event_to_pipeline(
    mock_registry: MagicMock,
    mock_embedder: AsyncMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    consumer = _make_consumer(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )

    msg = MagicMock()
    msg.value = {
        "event_type": "knowledge_source_synced",
        "source_id": str(SOURCE_ID),
        "tenant_id": TENANT_ID,
        "job_id": str(uuid4()),
        "items_processed": 10,
        "synced_at": datetime.now(tz=UTC).isoformat(),
    }
    await consumer._handle_message(msg)
    mock_embedder.embed_batch.assert_awaited_once()


@pytest.mark.asyncio
async def test_consumer_routes_deleted_event_to_deletion_handler(
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
    mock_registry: MagicMock,
    mock_embedder: AsyncMock,
) -> None:
    doc_id = "github:org/repo:abc123"
    consumer = _make_consumer(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )

    msg = MagicMock()
    msg.value = {
        "event_type": "knowledge_document_deleted",
        "source_id": str(SOURCE_ID),
        "tenant_id": TENANT_ID,
        "document_id": doc_id,
    }
    await consumer._handle_message(msg)
    mock_chunk_repo.list_by_document.assert_awaited_once_with(doc_id)


@pytest.mark.asyncio
async def test_consumer_skips_unknown_event_type_without_crash(
    mock_registry: MagicMock,
    mock_embedder: AsyncMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
) -> None:
    consumer = _make_consumer(
        mock_embedder, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_registry
    )

    msg = MagicMock()
    msg.value = {"event_type": "totally_unknown_event"}
    await consumer._handle_message(msg)  # must not raise
    mock_embedder.embed_batch.assert_not_awaited()
