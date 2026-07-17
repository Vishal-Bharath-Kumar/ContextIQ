"""IndexingPipeline — pure orchestration layer for the EP-008 indexing pipeline.

TASK-US027-04: Fetches chunks from a connector, embeds them, and persists the
results to Qdrant, OpenSearch, and PostgreSQL concurrently.  The class has no
I/O of its own so it can be exercised in tests without a live Kafka broker.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from src.connector_sdk.registry import ConnectorRegistry
from src.indexing.embedding.service import EmbeddingService
from src.indexing.repositories.chunk_repository import ChunkRepository
from src.indexing.schemas.chunk import ChunkMetadata, ChunkPayload
from src.indexing.stores.opensearch_indexer import OpenSearchIndexer
from src.indexing.stores.qdrant_indexer import QdrantIndexer
from src.knowledge_graph.schemas.events import ChunkIndexedEvent

if TYPE_CHECKING:
    from aiokafka import AIOKafkaProducer


class IndexingPipeline:
    """Orchestrates the embed → Qdrant upsert → OpenSearch index → PG upsert pipeline.

    All four store operations are wired together here; the caller (IndexingConsumer)
    only needs to invoke ``run_for_source`` with the identifiers extracted from the
    Kafka event.
    """

    def __init__(
        self,
        embedder: EmbeddingService,
        qdrant: QdrantIndexer,
        opensearch: OpenSearchIndexer,
        chunk_repo: ChunkRepository,
        registry: ConnectorRegistry,
        producer: AIOKafkaProducer | None = None,
    ) -> None:
        self._embedder = embedder
        self._qdrant = qdrant
        self._opensearch = opensearch
        self._chunk_repo = chunk_repo
        self._registry = registry
        self._producer = producer

    async def run_for_source(self, source_id: UUID, tenant_id: str) -> int:
        """Run the full indexing pipeline for one knowledge source.

        Steps
        -----
        1. Fetch raw chunks from the connector via the registry.
        2. Ensure the Qdrant collection and OpenSearch index exist (concurrent).
        3. Embed all chunks in parallel batches.
        4. Upsert vectors into Qdrant and bulk-index text into OpenSearch (concurrent).
        5. Upsert chunk metadata rows into PostgreSQL.

        Returns
        -------
        int
            Number of chunks successfully indexed.
        """
        connector = self._registry.get(str(source_id))
        chunks: list[ChunkPayload] = await connector.get_chunks()

        await asyncio.gather(
            self._qdrant.ensure_collection(source_id, tenant_id),
            self._opensearch.ensure_index(tenant_id),
        )

        indexed_chunks = await self._embedder.embed_batch(chunks)

        await asyncio.gather(
            self._qdrant.upsert(indexed_chunks, source_id, tenant_id),
            self._opensearch.bulk_index(indexed_chunks, tenant_id=tenant_id),
        )

        now = datetime.now(tz=UTC)
        metadata = [
            ChunkMetadata(
                chunk_id=c.payload.chunk_id,
                source_id=c.payload.source_id,
                tenant_id=c.payload.tenant_id,
                document_id=c.payload.document_id,
                embedding_model=c.model_id,
                token_count=c.payload.token_count,
                indexed_at=now,
            )
            for c in indexed_chunks
        ]
        await self._chunk_repo.upsert_batch(metadata)

        if self._producer is not None:
            for chunk in indexed_chunks:
                event = ChunkIndexedEvent(
                    chunk_id=chunk.payload.chunk_id,
                    source_id=chunk.payload.source_id,
                    tenant_id=chunk.payload.tenant_id,
                    document_id=chunk.payload.document_id,
                    text=chunk.payload.text,
                    token_count=chunk.payload.token_count,
                    embedding_model=chunk.model_id,
                    indexed_at=now,
                )
                await self._producer.send_and_wait(
                    "knowledge.chunk.indexed",
                    value=event.model_dump_json().encode("utf-8"),
                )

        return len(indexed_chunks)
