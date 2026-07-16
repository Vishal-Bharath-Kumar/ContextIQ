"""Unit tests for OpenSearchIndexer and DeletionHandler — TASK-US027-03.

All tests run without live stores:
  - AsyncOpenSearch is replaced with an AsyncMock.
  - ChunkRepository, QdrantIndexer, OpenSearchIndexer are replaced with AsyncMocks
    for DeletionHandler tests.
  - No network calls are made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.indexing.models.chunk import ChunkRecord
from src.indexing.schemas.chunk import ChunkPayload, IndexedChunk
from src.indexing.stores.deletion_handler import DeletionHandler
from src.indexing.stores.opensearch_indexer import (
    OpenSearchIndexer,
    OpenSearchSettings,
    index_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOURCE_ID = UUID("12345678-1234-5678-1234-567812345678")
TENANT_ID = "acme"


def _make_settings(**overrides: object) -> OpenSearchSettings:
    base: dict[str, object] = {
        "url": "http://localhost:9200",
        "username": "admin",
        "password": "admin",
        "bulk_size": 256,
        "index_prefix": "contextiq_chunks",
    }
    base.update(overrides)
    return OpenSearchSettings.model_construct(**base)  # type: ignore[arg-type]


def _make_indexed_chunk(text: str = "hello", doc_id: str = "doc:1") -> IndexedChunk:
    payload = ChunkPayload(
        source_id=SOURCE_ID,
        tenant_id=TENANT_ID,
        document_id=doc_id,
        text=text,
        token_count=1,
    )
    return IndexedChunk(payload=payload, vector=[0.1, 0.2, 0.3, 0.4], model_id="test")


def _make_chunk_record(document_id: str = "doc:1") -> ChunkRecord:
    record = MagicMock(spec=ChunkRecord)
    record.chunk_id = uuid4()
    record.document_id = document_id
    return record


# ---------------------------------------------------------------------------
# index_name helper
# ---------------------------------------------------------------------------


class TestIndexName:
    def test_format_uses_tenant_suffix(self) -> None:
        assert index_name("acme") == "contextiq_chunks_acme"

    def test_different_tenants_produce_different_names(self) -> None:
        assert index_name("acme") != index_name("beta")


# ---------------------------------------------------------------------------
# OpenSearchIndexer.ensure_index
# ---------------------------------------------------------------------------


class TestEnsureIndex:
    @pytest.mark.asyncio
    async def test_creates_index_when_absent(self) -> None:
        """Index is created with BM25 mappings when it does not exist."""
        settings = _make_settings()
        with patch("src.indexing.stores.opensearch_indexer.AsyncOpenSearch") as MockOS:
            client = AsyncMock()
            client.indices = AsyncMock()
            client.indices.exists = AsyncMock(return_value=False)
            client.indices.create = AsyncMock()
            MockOS.return_value = client

            indexer = OpenSearchIndexer(settings)
            await indexer.ensure_index(TENANT_ID)

        client.indices.create.assert_called_once()
        call_kwargs = client.indices.create.call_args.kwargs
        assert call_kwargs["index"] == index_name(TENANT_ID)
        props = call_kwargs["body"]["mappings"]["properties"]
        assert "text" in props
        assert props["text"]["type"] == "text"

    @pytest.mark.asyncio
    async def test_does_not_create_when_index_exists(self) -> None:
        """create is not called if the index already exists."""
        settings = _make_settings()
        with patch("src.indexing.stores.opensearch_indexer.AsyncOpenSearch") as MockOS:
            client = AsyncMock()
            client.indices = AsyncMock()
            client.indices.exists = AsyncMock(return_value=True)
            client.indices.create = AsyncMock()
            MockOS.return_value = client

            indexer = OpenSearchIndexer(settings)
            await indexer.ensure_index(TENANT_ID)

        client.indices.create.assert_not_called()


# ---------------------------------------------------------------------------
# OpenSearchIndexer.bulk_index
# ---------------------------------------------------------------------------


class TestBulkIndex:
    @pytest.mark.asyncio
    async def test_bulk_index_calls_async_bulk(self) -> None:
        """bulk_index delegates to helpers.async_bulk with correct actions."""
        settings = _make_settings()
        chunks = [_make_indexed_chunk(f"text {i}") for i in range(5)]

        with (
            patch("src.indexing.stores.opensearch_indexer.AsyncOpenSearch"),
            patch("src.indexing.stores.opensearch_indexer.helpers") as mock_helpers,
        ):
            mock_helpers.async_bulk = AsyncMock()

            indexer = OpenSearchIndexer(settings)
            await indexer.bulk_index(chunks, TENANT_ID)

        mock_helpers.async_bulk.assert_called_once()
        _, actions = mock_helpers.async_bulk.call_args.args
        assert len(actions) == 5
        for action, chunk in zip(actions, chunks, strict=True):
            assert action["_index"] == index_name(TENANT_ID)
            assert action["_id"] == str(chunk.payload.chunk_id)
            assert action["_source"]["text"] == chunk.payload.text
            assert action["_source"]["document_id"] == chunk.payload.document_id

    @pytest.mark.asyncio
    async def test_bulk_index_empty_list_calls_async_bulk_with_no_actions(self) -> None:
        """Calling bulk_index with an empty list issues an async_bulk call with 0 actions."""
        settings = _make_settings()

        with (
            patch("src.indexing.stores.opensearch_indexer.AsyncOpenSearch"),
            patch("src.indexing.stores.opensearch_indexer.helpers") as mock_helpers,
        ):
            mock_helpers.async_bulk = AsyncMock()

            indexer = OpenSearchIndexer(settings)
            await indexer.bulk_index([], TENANT_ID)

        mock_helpers.async_bulk.assert_called_once()
        _, actions = mock_helpers.async_bulk.call_args.args
        assert actions == []


# ---------------------------------------------------------------------------
# OpenSearchIndexer.delete_by_document
# ---------------------------------------------------------------------------


class TestDeleteByDocument:
    @pytest.mark.asyncio
    async def test_delete_by_query_called_with_correct_document_id(self) -> None:
        """delete_by_query targets the correct index and document_id term."""
        settings = _make_settings()
        with patch("src.indexing.stores.opensearch_indexer.AsyncOpenSearch") as MockOS:
            client = AsyncMock()
            client.delete_by_query = AsyncMock()
            MockOS.return_value = client

            indexer = OpenSearchIndexer(settings)
            await indexer.delete_by_document("doc:1", TENANT_ID)

        client.delete_by_query.assert_called_once()
        call_kwargs = client.delete_by_query.call_args.kwargs
        assert call_kwargs["index"] == index_name(TENANT_ID)
        assert call_kwargs["body"]["query"]["term"]["document_id"] == "doc:1"


# ---------------------------------------------------------------------------
# DeletionHandler
# ---------------------------------------------------------------------------


class TestDeletionHandler:
    def _make_handler(
        self,
        records: list[MagicMock],
    ) -> tuple[DeletionHandler, AsyncMock, AsyncMock, AsyncMock]:
        chunk_repo = AsyncMock()
        chunk_repo.list_by_document = AsyncMock(return_value=records)
        chunk_repo.delete_by_document = AsyncMock()

        qdrant = AsyncMock()
        qdrant.delete_by_document = AsyncMock()

        opensearch = AsyncMock()
        opensearch.delete_by_document = AsyncMock()

        handler = DeletionHandler(
            chunk_repo=chunk_repo,
            qdrant=qdrant,
            opensearch=opensearch,
        )
        return handler, chunk_repo, qdrant, opensearch

    @pytest.mark.asyncio
    async def test_handle_calls_all_three_stores_in_order(self) -> None:
        """Qdrant delete, OpenSearch delete, and PostgreSQL delete are called in order."""
        records = [_make_chunk_record(), _make_chunk_record()]
        handler, chunk_repo, qdrant, opensearch = self._make_handler(records)

        call_order: list[str] = []
        qdrant.delete_by_document.side_effect = lambda *a, **kw: call_order.append("qdrant")  # type: ignore[return-value]
        opensearch.delete_by_document.side_effect = lambda *a, **kw: call_order.append("opensearch")  # type: ignore[return-value]
        chunk_repo.delete_by_document.side_effect = lambda *a, **kw: call_order.append("pg")  # type: ignore[return-value]

        await handler.handle("doc:1", SOURCE_ID, TENANT_ID)

        assert call_order == ["qdrant", "opensearch", "pg"]

    @pytest.mark.asyncio
    async def test_handle_passes_correct_chunk_ids_to_qdrant(self) -> None:
        """Qdrant receives the chunk_ids fetched from PostgreSQL."""
        records = [_make_chunk_record(), _make_chunk_record()]
        handler, _, qdrant, _ = self._make_handler(records)

        await handler.handle("doc:1", SOURCE_ID, TENANT_ID)

        qdrant.delete_by_document.assert_called_once()
        _, _, _, chunk_ids = qdrant.delete_by_document.call_args.args
        assert chunk_ids == [r.chunk_id for r in records]

    @pytest.mark.asyncio
    async def test_handle_with_zero_chunks_completes_without_error(self) -> None:
        """handle() with no existing chunks exits early without calling any store.

        DeletionHandler guards against empty chunk lists internally: when
        PostgreSQL returns no rows there is nothing to delete, so no external
        store calls are issued.
        """
        handler, chunk_repo, qdrant, opensearch = self._make_handler([])

        # Should not raise
        await handler.handle("doc:missing", SOURCE_ID, TENANT_ID)

        qdrant.delete_by_document.assert_not_called()
        opensearch.delete_by_document.assert_not_called()
        chunk_repo.delete_by_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_passes_document_id_and_tenant_to_opensearch(self) -> None:
        """OpenSearch delete receives the correct document_id and tenant_id."""
        records = [_make_chunk_record()]
        handler, _, _, opensearch = self._make_handler(records)

        await handler.handle("doc:42", SOURCE_ID, TENANT_ID)

        opensearch.delete_by_document.assert_called_once_with("doc:42", TENANT_ID)

    @pytest.mark.asyncio
    async def test_handle_passes_document_id_to_pg(self) -> None:
        """PostgreSQL delete receives the correct document_id."""
        records = [_make_chunk_record()]
        handler, chunk_repo, _, _ = self._make_handler(records)

        await handler.handle("doc:99", SOURCE_ID, TENANT_ID)

        chunk_repo.delete_by_document.assert_called_once_with("doc:99")
