"""IndexingPipeline — pure orchestration layer for the EP-008 indexing pipeline.

TASK-US027-04: Fetches chunks from a connector, embeds them, and persists the
results to Qdrant, OpenSearch, and PostgreSQL concurrently.  The class has no
I/O of its own so it can be exercised in tests without a live Kafka broker.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.registry import ConnectorRegistry
from src.indexing.embedding.service import EmbeddingService
from src.indexing.repositories.chunk_repository import ChunkRepository
from src.indexing.schemas.chunk import ChunkMetadata, ChunkPayload
from src.indexing.stores.opensearch_indexer import OpenSearchIndexer
from src.indexing.stores.qdrant_indexer import QdrantIndexer
from src.knowledge_graph.schemas.events import ChunkIndexedEvent

if TYPE_CHECKING:
    from aiokafka import AIOKafkaProducer
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# connector_type -> KnowledgeSourceRecord.scope field name on each connector's
# own config class. Mirrors HealthCheckService's per-source config injection
# pattern (each knowledge source has its own Vault path + scope; the
# entry-point-discovered ConnectorRegistry only holds one shared, unscoped
# instance per connector *type* and cannot be used here).
_SCOPE_CONFIG_FIELD: dict[str, str] = {
    "github": "repos",
    "jira": "projects",
    "confluence": "spaces",
    "grafana": "dashboard_uids",
}


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
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._embedder = embedder
        self._qdrant = qdrant
        self._opensearch = opensearch
        self._chunk_repo = chunk_repo
        self._registry = registry
        self._producer = producer
        # Optional: enables lazily building + registering a per-source
        # connector (from the knowledge_sources table) the first time a
        # source_id isn't already in the registry — e.g. a source synced for
        # the first time after this service started. None in unit tests that
        # pre-populate the registry mock directly.
        self._session_factory = session_factory

    async def run_for_source(self, source_id: UUID, tenant_id: str) -> int:
        """Run the full indexing pipeline for one knowledge source.

        Steps
        -----
        1. Fetch raw chunks from the connector via the registry (lazily
           building + registering a per-source connector on first use).
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
        if connector is None and self._session_factory is not None:
            connector = await self._load_and_register_source_connector(source_id)

        if connector is None:
            logger.warning(
                "indexing_no_connector_registered",
                extra={"source_id": str(source_id)},
            )
            chunks: list[ChunkPayload] = []
        else:
            get_chunks = getattr(connector, "get_chunks", None)
            if get_chunks is None:
                logger.warning(
                    "connector_missing_get_chunks",
                    extra={
                        "source_id": str(source_id),
                        "connector_cls": type(connector).__name__,
                    },
                )
                chunks = []
            else:
                chunks = await get_chunks(source_id=source_id, tenant_id=tenant_id)

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

    async def close(self) -> None:
        """Close external clients owned by this pipeline instance."""
        await asyncio.gather(
            self._qdrant.close(),
            self._opensearch.close(),
        )

    async def _load_and_register_source_connector(
        self, source_id: UUID
    ) -> BaseConnector | None:
        """Build, authenticate, and register a connector for one knowledge source.

        Looks up the ``knowledge_sources`` row for *source_id* (the table the
        Admin Portal's Add Connector wizard writes to — NOT the separate,
        legacy ``connector_config`` table used by the agent retrieval path's
        ``ConnectorLoader``), builds the matching connector class with that
        source's own ``credentials_vault_path`` and ``scope`` injected (same
        per-source override pattern as ``HealthCheckService``), authenticates
        it, and registers it under ``str(source_id)`` so subsequent syncs
        reuse it via ``self._registry.get()``.

        Returns ``None`` (never raises) if the source doesn't exist, its
        connector type has no implementation, or authentication fails — the
        caller treats a ``None`` connector as "0 chunks" rather than crashing.
        """
        # Imported lazily to avoid a hard import-time dependency from the
        # indexing package on the knowledge_sources/agents packages.
        from src.agents.retrieval.connector_loader import CONNECTOR_CLASS_MAP
        from src.knowledge_sources.config import KnowledgeSourceSettings
        from src.knowledge_sources.repositories.knowledge_source_repository import (
            KnowledgeSourceRepository,
        )

        assert self._session_factory is not None  # narrows type for mypy; checked by caller
        async with self._session_factory() as session:
            record = await KnowledgeSourceRepository(session).get_by_id(source_id)

        if record is None:
            return None

        mapping = CONNECTOR_CLASS_MAP.get(record.connector_type)
        if mapping is None:
            logger.warning(
                "indexing_connector_type_not_implemented",
                extra={"source_id": str(source_id), "connector_type": record.connector_type},
            )
            return None
        connector_cls, config_cls = mapping
        vault_settings = KnowledgeSourceSettings()

        scope_field = _SCOPE_CONFIG_FIELD.get(record.connector_type)
        config_kwargs: dict[str, object] = {
            "vault_path": record.credentials_vault_path,
            # Mirror HealthCheckService behavior: connector-specific env vars
            # may be absent in this runtime, so inject shared knowledge-source
            # AppRole settings explicitly.
            "vault_addr": vault_settings.vault_addr,
            "vault_role_id": vault_settings.vault_role_id,
            "vault_secret_id": vault_settings.vault_secret_id,
        }
        if scope_field is not None:
            config_kwargs[scope_field] = [record.scope]

        try:
            connector = connector_cls(config=config_cls(**config_kwargs))
        except Exception:
            logger.warning(
                "indexing_connector_config_build_failed",
                extra={
                    "source_id": str(source_id),
                    "connector_type": record.connector_type,
                    "scope_field": scope_field,
                },
                exc_info=True,
            )
            return None

        try:
            await connector.authenticate()
        except Exception:
            logger.warning(
                "indexing_connector_auth_failed",
                extra={"source_id": str(source_id), "connector_type": record.connector_type},
                exc_info=True,
            )
            return None

        self._registry.register(str(source_id), connector)
        return connector
