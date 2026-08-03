"""SQLAlchemy 2.x async ORM for the `chunk_index` table — TASK-US027-01.

This model is the PostgreSQL metadata store for indexed text chunks produced
by the EP-008 indexing pipeline.  Each row tracks a single embedded chunk
alongside its source, tenant, embedding model, and token count.

The FK to `knowledge_sources.id` is intentionally omitted as a database-level
constraint.  At high ingestion throughput, FK validation on every insert adds
lock contention on the parent table; referential integrity is guaranteed at
the application layer before the indexing pipeline is dispatched.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class ChunkRecord(Base):
    __tablename__ = "chunk_index"

    chunk_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True
    )
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="FK to knowledge_sources.id (not enforced as FK for write throughput)",
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_id: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
