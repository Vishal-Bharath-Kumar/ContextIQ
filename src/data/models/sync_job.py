from __future__ import annotations
import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.base import Base


class SyncStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class SyncJob(Base):
    __tablename__ = "sync_job"

    id:           Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    connector_id: Mapped[uuid.UUID]        = mapped_column(ForeignKey("connector_config.id", ondelete="CASCADE"), nullable=False)
    status:       Mapped[SyncStatus]       = mapped_column(Enum(SyncStatus, name="sync_status_enum"), nullable=False, default=SyncStatus.PENDING, server_default=text("'pending'"))
    started_at:   Mapped[datetime | None]  = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at:  Mapped[datetime | None]  = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    items_synced: Mapped[int]              = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    items_failed: Mapped[int]              = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    error_log:    Mapped[str | None]       = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str]              = mapped_column(String(64), nullable=False)
    created_at:   Mapped[datetime]         = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    connector: Mapped[ConnectorConfig] = relationship("ConnectorConfig", back_populates="sync_jobs")


from src.data.models.connector_config import ConnectorConfig  # noqa: E402
