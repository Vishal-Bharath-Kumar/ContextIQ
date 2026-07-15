"""
AdminAuditRepository — writes SHA-256-chained rows to admin_audit_log.

AC-1: append one row per mutating Admin API action.
AC-6: each row stores row_hash = SHA-256(prev_hash || canonical_json(row)).
The calling route handler owns the transaction; this repository only flushes.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.hash_chain import (
    GENESIS_PREV_HASH,
    compute_row_hash,
    row_fields_for_hashing,
)
from src.audit.admin_audit_log.models import AdminAuditLog
from src.audit.admin_audit_log.schemas import AuditLogCreateRequest

logger = logging.getLogger(__name__)


class AdminAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(self, request: AuditLogCreateRequest) -> AdminAuditLog:
        """
        AC-1: Append one audit entry to admin_audit_log.
        AC-6: Compute row_hash = SHA-256(prev_hash || canonical_json(this_row)).

        The session is NOT committed here — the calling route handler owns the
        transaction so that the audit entry and the business-logic write are
        committed atomically.
        """
        timestamp = datetime.now(timezone.utc)
        prev_hash = await self._latest_row_hash()

        fields = row_fields_for_hashing(
            action=request.action,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            actor_user_id=request.actor_user_id,
            ip_address=request.ip_address,
            before_state=request.before_state,
            after_state=request.after_state,
            timestamp=timestamp,
        )
        row_hash = compute_row_hash(prev_hash, fields)

        entry = AdminAuditLog(
            id=uuid.uuid4(),
            action=request.action,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            actor_user_id=request.actor_user_id,
            ip_address=request.ip_address,
            before_state=request.before_state,
            after_state=request.after_state,
            timestamp=timestamp,
            row_hash=row_hash,
        )
        self._session.add(entry)
        await self._session.flush()   # assign DB id without committing
        logger.debug(
            "audit_log.append action=%s resource=%s/%s actor=%s",
            request.action,
            request.resource_type,
            request.resource_id,
            request.actor_user_id,
        )
        return entry

    async def _latest_row_hash(self) -> str:
        """
        Return the `row_hash` of the most recently inserted row,
        or GENESIS_PREV_HASH when the table is empty (AC-6).
        """
        result = await self._session.execute(
            select(AdminAuditLog.row_hash)
            .order_by(AdminAuditLog.timestamp.desc(), AdminAuditLog.id.desc())
            .limit(1)
        )
        latest: str | None = result.scalar_one_or_none()
        return latest if latest is not None else GENESIS_PREV_HASH
