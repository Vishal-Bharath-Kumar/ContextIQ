"""Pydantic v2 schemas for knowledge-graph Kafka events — TASK-US028-01, TASK-US030-01.

Defines:
  ChunkIndexedEvent           — emitted by IndexingPipeline after a chunk is indexed,
                                consumed by EntityConsumer (TASK-US028-04).
  EntityExtractionFailedEvent — emitted to the dead-letter topic when a chunk
                                exhausts all retry attempts.
  TombstoneEvent              — deletion signal for AC-3 tombstone pattern.
  GraphUpdatedEvent           — emitted after each incremental update batch (AC-6).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChunkIndexedEvent(BaseModel):
    """Emitted by IndexingPipeline (US-027) after a chunk is written to Qdrant,
    OpenSearch, and PostgreSQL.  Consumed by EntityConsumer (TASK-US028-04).
    """

    model_config = ConfigDict(frozen=True)

    event_type: str = "knowledge_chunk_indexed"
    chunk_id: UUID
    source_id: UUID
    tenant_id: str
    document_id: str
    text: str
    token_count: int
    embedding_model: str
    indexed_at: datetime


class ChunkRetryEnvelope(BaseModel):
    """Wraps a ``ChunkIndexedEvent`` with a retry attempt counter.

    Published to the retry topic by ``EntityConsumer`` when extraction fails
    and the attempt count has not yet reached ``max_retries``.
    """

    model_config = ConfigDict(frozen=True)

    attempt: int
    original: ChunkIndexedEvent


class EntityExtractionFailedEvent(BaseModel):
    """Emitted to the dead-letter topic when a chunk exhausts all retry attempts."""

    model_config = ConfigDict(frozen=True)

    event_type: str = "entity_extraction_failed"
    chunk_id: UUID
    source_id: UUID
    tenant_id: str
    error: str
    failed_at: datetime
    attempt: int


class TombstoneEvent(BaseModel):
    """
    Deletion signal consumed by GraphUpdaterConsumer to remove relationships
    for a deleted entity (AC-3 tombstone pattern).
    Emitted by the connector sync pipeline when a document is removed.
    """

    model_config = ConfigDict(frozen=True)

    event_type: str = "knowledge_entity_tombstone"
    entity_id: str = Field(min_length=16, max_length=16)
    source_id: UUID
    tenant_id: str
    document_id: str
    deleted_at: datetime


class GraphUpdatedEvent(BaseModel):
    """
    Emitted to `knowledge.graph.updated` after each incremental update batch (AC-6).
    Downstream consumers (e.g. traversal cache invalidation) subscribe to this topic.
    """

    model_config = ConfigDict(frozen=True)

    event_type: str = "knowledge_graph_updated"
    source_id: UUID
    tenant_id: str
    chunks_processed: int
    entities_upserted: int
    relationships_upserted: int
    relationships_expired: int
    updated_at: datetime
