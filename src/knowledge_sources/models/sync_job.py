"""SQLAlchemy 2.x async ORM for the `sync_jobs` table — TASK-US026-01.

Tracks the lifecycle of each sync operation triggered for a KnowledgeSource.
Status transitions: running → succeeded | failed.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, text
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class SyncJobStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


_SYNC_JOB_STATUS = PgEnum(
    "running", "succeeded", "failed",
    name="sync_job_status_enum",
)


class SyncJobRecord(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        _SYNC_JOB_STATUS,
        nullable=False,
        server_default="running",
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    is_full_sync: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    started_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    items_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
