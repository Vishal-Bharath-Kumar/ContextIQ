"""
AdminAuditLog SQLAlchemy ORM model — TASK-US044-01.

AC-1: unified audit table for every mutating Admin API action.
AC-2: row-level immutability enforced by PostgreSQL trigger (see migration 0019).
AC-6: tamper-evident SHA-256 hash chain stored in ``row_hash``.

IMPORTANT: application code must NEVER issue UPDATE or DELETE against this
table.  The database-level trigger raises a PL/pgSQL exception on any attempt;
this class is the final documentation of that contract.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# BUG FIX (spec): the spec imported from `src.db.base` which does not exist
# in this project.  The DeclarativeBase is at `src.data.models.base`.
from src.data.models.base import Base


class AdminAuditLog(Base):
    """
    Unified audit log for all mutating Admin API actions.

    Columns
    -------
    id            Primary key (UUID v4, Python-generated).
    action        ``AdminActionType`` value, e.g. ``"policy.created"`` (AC-1).
    resource_type Domain of the mutated resource, e.g. ``"policy"`` (AC-1).
    resource_id   Identifier of the mutated resource (AC-1).
    actor_user_id JWT ``sub`` claim of the performing user (AC-1).
    ip_address    Client IP address from the request (AC-1).
    before_state  JSONB snapshot of the resource before the mutation (AC-1).
    after_state   JSONB snapshot of the resource after the mutation (AC-1).
    timestamp     UTC datetime of the action (AC-1).
    row_hash      SHA-256 of (prev_hash + canonical_json(this_row)) (AC-6).
    """

    __tablename__ = "admin_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        index=True,
    )
    ip_address: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    before_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    after_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )
    # AC-6: SHA-256 hex digest (64 chars) of this row's content chained
    # to the previous row's hash.  See src/audit/admin_audit_log/hash_chain.py.
    row_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
