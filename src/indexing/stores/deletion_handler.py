"""DeletionHandler — coordinates stale-embedding removal across all stores (AC-7).

TASK-US027-03: Handles ``knowledge.document.deleted`` Kafka events by removing
chunk data from Qdrant, OpenSearch, and PostgreSQL within the 5-minute SLA.
"""
from __future__ import annotations

from uuid import UUID

from src.indexing.repositories.chunk_repository import ChunkRepository
from src.indexing.stores.opensearch_indexer import OpenSearchIndexer
from src.indexing.stores.qdrant_indexer import QdrantIndexer


class DeletionHandler:
    """Orchestrates deletion of stale chunk data across all three stores.

    Processing order:
    1. Fetch chunk IDs from PostgreSQL (authoritative source of truth).
    2. Delete vector points from Qdrant (most expensive to reconstruct).
    3. Delete keyword documents from OpenSearch.
    4. Delete metadata rows from PostgreSQL.

    Partial failure is safe because the Kafka consumer re-delivers the event
    on retry, making the entire handler idempotent.
    """

    def __init__(
        self,
        chunk_repo: ChunkRepository,
        qdrant: QdrantIndexer,
        opensearch: OpenSearchIndexer,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._qdrant = qdrant
        self._opensearch = opensearch

    async def handle(
        self,
        document_id: str,
        source_id: UUID,
        tenant_id: str,
    ) -> None:
        """Remove all chunk data for a deleted document from every store.

        If no chunks are found in PostgreSQL the handler exits early without
        issuing any deletion calls to external stores.
        """
        records = await self._chunk_repo.list_by_document(document_id)
        chunk_ids = [r.chunk_id for r in records]

        if not chunk_ids:
            return

        # Stores are updated in dependency order: vector store first (most
        # expensive to re-create), then keyword store, then metadata.
        await self._qdrant.delete_by_document(document_id, source_id, tenant_id, chunk_ids)
        await self._opensearch.delete_by_document(document_id, tenant_id)
        await self._chunk_repo.delete_by_document(document_id)
