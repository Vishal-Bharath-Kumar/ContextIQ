"""SQLAlchemy ORM model for the model_audit_log table.

Records every mutating model registry event — registration, status change,
and routing weight update — with actor_user_id and timestamp (AC-6 / US-041).

TASK-US041-05
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.model_registry.models.base import Base


class ModelAuditLog(Base):
    """
    AC-6: immutable record of every model registry or routing weight mutation.

    ``model_id`` is stored as a plain string (not a FK) so audit history is
    preserved even after the model record is deleted.  Routing weight events
    use the prefix ``routing:`` to avoid collision with real model IDs.
    """

    __tablename__ = "model_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
