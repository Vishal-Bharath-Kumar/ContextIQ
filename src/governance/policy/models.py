"""SQLAlchemy ORM model for governance policy versioning.

Stores every policy version ever submitted to ContextIQ.
One row per (policy_group, version) pair.
At most one row per policy_group may have status='active' at any time —
enforced at the service layer, not by a DB constraint.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class PolicyRecord(Base):
    """Persisted policy version row in the ``policy_definitions`` table."""

    __tablename__ = "policy_definitions"
    __table_args__ = (
        UniqueConstraint("policy_group", "version", name="uq_policy_group_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_group: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rego_body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")

    # Audit fields (AC-5)
    author: Mapped[str] = mapped_column(String(256), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
    )
