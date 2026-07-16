"""Pydantic v2 schemas for the EP-008 indexing pipeline — TASK-US027-01.

Three schemas cover the full lifecycle of a chunk as it moves through the
indexing pipeline:

  ChunkPayload   — raw text chunk produced by a connector, ready for embedding
  IndexedChunk   — payload paired with its generated embedding vector
  ChunkMetadata  — row written to PostgreSQL after successful indexing
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ChunkPayload(BaseModel):
    """Raw text chunk produced by a connector, ready for embedding."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    tenant_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(
        description="Connector-native document identifier, e.g. 'github:owner/repo:sha'",
        min_length=1,
        max_length=512,
    )
    text: str = Field(min_length=1)
    token_count: int = Field(ge=1)
    metadata: dict[str, object] = Field(default_factory=dict)


class ChunkMetadata(BaseModel):
    """Row written to PostgreSQL after successful indexing."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    source_id: UUID
    tenant_id: str
    document_id: str
    embedding_model: str
    token_count: int
    indexed_at: datetime


class IndexedChunk(BaseModel):
    """Combines raw payload with its generated embedding vector."""

    model_config = ConfigDict(frozen=True)

    payload: ChunkPayload
    vector: list[float]
    model_id: str
