"""Pydantic v2 schemas for Kafka events consumed by the indexing pipeline.

TASK-US027-04: Defines the event payloads for:
  SourceSyncedEvent      — emitted by SyncJobExecutor on knowledge.source.synced
  DocumentDeletedEvent   — emitted on knowledge.document.deleted
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SourceSyncedEvent(BaseModel):
    """Payload for the ``knowledge_source_synced`` event."""

    model_config = ConfigDict(frozen=True)

    event_type: str  # "knowledge_source_synced"
    source_id: UUID
    tenant_id: str
    job_id: UUID
    items_processed: int
    synced_at: datetime


class DocumentDeletedEvent(BaseModel):
    """Payload for the ``knowledge_document_deleted`` event."""

    model_config = ConfigDict(frozen=True)

    event_type: str  # "knowledge_document_deleted"
    source_id: UUID
    tenant_id: str
    document_id: str
