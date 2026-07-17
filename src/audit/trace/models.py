"""SQLAlchemy ORM model for the execution_traces search index — TASK-US034-01.

Full trace JSON lives in MinIO; this table holds only the searchable metadata
columns needed by US-035 (Replay Explorer) filters (AC-4).

Indexed on: request_id (PK/unique), user_id, timestamp, intent, and the
composite pairs (user_id, timestamp) and (tenant_id, timestamp).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class TraceRecord(Base):
    """PostgreSQL search index for execution traces (AC-4).

    Full trace JSON lives in MinIO; this table holds only searchable metadata.

    Indexed on: request_id (unique), user_id, timestamp, intent (AC-4).
    """

    __tablename__ = "execution_traces"

    # Search columns (AC-4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    intent: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Governance summary columns — support US-035 search filters
    model_selected: Mapped[str | None] = mapped_column(String(128), nullable=True)
    governance_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    opa_denied_count: Mapped[int] = mapped_column(Integer, default=0)

    # MinIO pointer
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    object_version: Mapped[str] = mapped_column(
        String(256), nullable=False, default=""
    )

    # Composite indexes for common US-035 search patterns
    __table_args__ = (
        Index("ix_traces_user_timestamp", "user_id", "timestamp"),
        Index("ix_traces_tenant_timestamp", "tenant_id", "timestamp"),
    )
