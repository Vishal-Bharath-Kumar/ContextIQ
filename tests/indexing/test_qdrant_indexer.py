"""Unit tests for QdrantIndexer — TASK-US027-03.

All tests run without a live Qdrant instance:
  - AsyncQdrantClient is replaced with an AsyncMock.
  - No network calls are made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.indexing.schemas.chunk import ChunkPayload, IndexedChunk
from src.indexing.stores.qdrant_indexer import (
    QdrantIndexer,
    QdrantSettings,
    collection_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOURCE_ID = UUID("12345678-1234-5678-1234-567812345678")
TENANT_ID = "acme"


def _make_settings(**overrides: object) -> QdrantSettings:
    base: dict[str, object] = {
        "url": "http://localhost:6333",
        "api_key": None,
        "vector_size": 4,
        "batch_size": 128,
        "distance": "Cosine",
    }
    base.update(overrides)
    return QdrantSettings.model_construct(**base)  # type: ignore[arg-type]


def _make_indexed_chunk(text: str = "hello") -> IndexedChunk:
    payload = ChunkPayload(
        source_id=SOURCE_ID,
        tenant_id=TENANT_ID,
        document_id="doc:1",
        text=text,
        token_count=1,
    )
    return IndexedChunk(payload=payload, vector=[0.1, 0.2, 0.3, 0.4], model_id="test")


def _mock_upsert_result() -> MagicMock:
    from qdrant_client.http.models import UpdateStatus

    result = MagicMock()
    result.status = UpdateStatus.COMPLETED
    return result


# ---------------------------------------------------------------------------
# collection_name helper
# ---------------------------------------------------------------------------


class TestCollectionName:
    def test_format_matches_hex_tenant(self) -> None:
        name = collection_name(SOURCE_ID, "acme")
        assert name == f"{SOURCE_ID.hex}_acme"

    def test_no_dashes_in_name(self) -> None:
        name = collection_name(SOURCE_ID, "acme")
        assert "-" not in name

    def test_different_tenants_produce_different_names(self) -> None:
        assert collection_name(SOURCE_ID, "acme") != collection_name(SOURCE_ID, "beta")


# ---------------------------------------------------------------------------
# QdrantIndexer.ensure_collection
# ---------------------------------------------------------------------------


class TestEnsureCollection:
    @pytest.mark.asyncio
    async def test_creates_collection_when_absent(self) -> None:
        """Collection is created when it does not exist."""
        settings = _make_settings()
        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.collection_exists = AsyncMock(return_value=False)
            client.create_collection = AsyncMock()
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.ensure_collection(SOURCE_ID, TENANT_ID)

        client.create_collection.assert_called_once()
        call_kwargs = client.create_collection.call_args.kwargs
        assert call_kwargs["collection_name"] == collection_name(SOURCE_ID, TENANT_ID)

    @pytest.mark.asyncio
    async def test_idempotent_when_collection_exists(self) -> None:
        """Calling ensure_collection twice when the collection already exists does not raise."""
        settings = _make_settings()
        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.collection_exists = AsyncMock(return_value=True)
            client.create_collection = AsyncMock()
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.ensure_collection(SOURCE_ID, TENANT_ID)
            await indexer.ensure_collection(SOURCE_ID, TENANT_ID)

        client.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_not_called_when_exists_on_second_call(self) -> None:
        """Second call when collection already exists does not attempt creation."""
        settings = _make_settings()
        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            # First call: does not exist; second call: exists.
            client.collection_exists = AsyncMock(side_effect=[False, True])
            client.create_collection = AsyncMock()
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.ensure_collection(SOURCE_ID, TENANT_ID)
            await indexer.ensure_collection(SOURCE_ID, TENANT_ID)

        assert client.create_collection.call_count == 1


# ---------------------------------------------------------------------------
# QdrantIndexer.upsert — batching
# ---------------------------------------------------------------------------


class TestUpsert:
    @pytest.mark.asyncio
    async def test_300_chunks_split_into_3_batches(self) -> None:
        """300 chunks with batch_size=128 → 3 upsert calls (128 + 128 + 44)."""
        settings = _make_settings(batch_size=128)
        chunks = [_make_indexed_chunk(f"text {i}") for i in range(300)]

        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.upsert = AsyncMock(return_value=_mock_upsert_result())
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.upsert(chunks, SOURCE_ID, TENANT_ID)

        assert client.upsert.call_count == 3
        sizes = [
            len(call.kwargs["points"]) for call in client.upsert.call_args_list
        ]
        assert sizes == [128, 128, 44]

    @pytest.mark.asyncio
    async def test_single_batch_when_chunks_under_limit(self) -> None:
        """Fewer chunks than batch_size → exactly one upsert call."""
        settings = _make_settings(batch_size=128)
        chunks = [_make_indexed_chunk(f"text {i}") for i in range(50)]

        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.upsert = AsyncMock(return_value=_mock_upsert_result())
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.upsert(chunks, SOURCE_ID, TENANT_ID)

        client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_raises_on_non_completed_status(self) -> None:
        """RuntimeError is raised when Qdrant returns a non-COMPLETED status."""
        from qdrant_client.http.models import UpdateStatus

        settings = _make_settings(batch_size=128)
        chunks = [_make_indexed_chunk()]

        bad_result = MagicMock()
        bad_result.status = UpdateStatus.ACKNOWLEDGED

        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.upsert = AsyncMock(return_value=bad_result)
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            with pytest.raises(RuntimeError, match="unexpected status"):
                await indexer.upsert(chunks, SOURCE_ID, TENANT_ID)

    @pytest.mark.asyncio
    async def test_upsert_uses_correct_collection_name(self) -> None:
        """The upsert call targets the correct collection name."""
        settings = _make_settings(batch_size=128)
        chunks = [_make_indexed_chunk()]

        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.upsert = AsyncMock(return_value=_mock_upsert_result())
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.upsert(chunks, SOURCE_ID, TENANT_ID)

        call_kwargs = client.upsert.call_args.kwargs
        assert call_kwargs["collection_name"] == collection_name(SOURCE_ID, TENANT_ID)

    @pytest.mark.asyncio
    async def test_point_payload_contains_required_fields(self) -> None:
        """Each PointStruct payload contains source_id, tenant_id, document_id, text."""
        settings = _make_settings(batch_size=128)
        chunk = _make_indexed_chunk("sample text")

        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.upsert = AsyncMock(return_value=_mock_upsert_result())
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.upsert([chunk], SOURCE_ID, TENANT_ID)

        points = client.upsert.call_args.kwargs["points"]
        assert len(points) == 1
        payload = points[0].payload
        assert payload["source_id"] == str(SOURCE_ID)
        assert payload["tenant_id"] == TENANT_ID
        assert payload["document_id"] == "doc:1"
        assert payload["text"] == "sample text"


# ---------------------------------------------------------------------------
# QdrantIndexer.delete_by_document
# ---------------------------------------------------------------------------


class TestDeleteByDocument:
    @pytest.mark.asyncio
    async def test_delete_called_with_chunk_ids(self) -> None:
        """delete is called with stringified chunk UUIDs."""
        chunk_ids = [uuid4(), uuid4()]
        settings = _make_settings()

        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.delete = AsyncMock()
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.delete_by_document("doc:1", SOURCE_ID, TENANT_ID, chunk_ids)

        client.delete.assert_called_once()
        call_kwargs = client.delete.call_args.kwargs
        assert call_kwargs["collection_name"] == collection_name(SOURCE_ID, TENANT_ID)
        assert set(call_kwargs["points_selector"]) == {str(c) for c in chunk_ids}

    @pytest.mark.asyncio
    async def test_empty_chunk_ids_skips_delete(self) -> None:
        """delete_by_document with no chunk IDs does not call Qdrant client."""
        settings = _make_settings()

        with patch("src.indexing.stores.qdrant_indexer.AsyncQdrantClient") as MockClient:
            client = AsyncMock()
            client.delete = AsyncMock()
            MockClient.return_value = client

            indexer = QdrantIndexer(settings)
            await indexer.delete_by_document("doc:1", SOURCE_ID, TENANT_ID, [])

        client.delete.assert_not_called()
