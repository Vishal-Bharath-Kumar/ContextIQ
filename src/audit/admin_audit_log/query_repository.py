"""
AuditLogQueryRepository — filtered + cursor-paginated read queries.

Uses the read replica (AC-6: keep reporting traffic off the primary).
Cursor encoding stores both timestamp AND id so that keyset pagination
works correctly with ORDER BY timestamp ASC, id ASC.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.models import AdminAuditLog

_PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# Opaque cursor helpers (encodes both timestamp and id for correct keyset pagination)
# ---------------------------------------------------------------------------

def encode_cursor(timestamp: datetime, row_id: uuid.UUID) -> str:
    """
    Return a URL-safe base64-encoded cursor token encoding (timestamp, id).

    BUG FIX: storing only id in the cursor and filtering `id > cursor_id`
    is broken when sorting by (timestamp ASC, id ASC) because UUID v4 ids
    are random — rows with a later timestamp but a smaller UUID than the
    cursor would be silently skipped.  Both fields are required.
    """
    payload = json.dumps({"ts": timestamp.isoformat(), "id": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode an opaque cursor token into (timestamp, id)."""
    # Restore base64 padding
    padding = "=" * (-len(cursor) % 4)
    data: dict[str, Any] = json.loads(base64.urlsafe_b64decode(cursor + padding).decode())
    return datetime.fromisoformat(data["ts"]), uuid.UUID(data["id"])


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class AuditLogQueryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filtered(
        self,
        *,
        actor_user_id: str | None       = None,
        action:        str | None       = None,
        resource_type: str | None       = None,
        resource_id:   str | None       = None,
        date_from:     datetime | None  = None,
        date_to:       datetime | None  = None,
        cursor:        str | None       = None,   # opaque token from encode_cursor()
        limit:         int              = _PAGE_SIZE,
    ) -> list[AdminAuditLog]:
        """
        AC-4: Filtered + keyset-paginated query.

        Cursor pagination: pass the ``next_cursor`` value from the previous
        response as ``cursor`` to fetch the next page.  The cursor encodes
        both the last row's timestamp and id so that the keyset WHERE clause
        works correctly with ORDER BY timestamp DESC, id DESC (newest first).
        """
        conditions = []

        if actor_user_id:
            conditions.append(AdminAuditLog.actor_user_id == actor_user_id)
        if action:
            conditions.append(AdminAuditLog.action == action)
        if resource_type:
            conditions.append(AdminAuditLog.resource_type == resource_type)
        if resource_id:
            conditions.append(AdminAuditLog.resource_id == resource_id)
        if date_from:
            conditions.append(AdminAuditLog.timestamp >= date_from)
        if date_to:
            conditions.append(AdminAuditLog.timestamp <= date_to)

        if cursor is not None:
            cursor_ts, cursor_id = decode_cursor(cursor)
            # Correct keyset for DESC: (ts < cursor_ts) OR (ts == cursor_ts AND id < cursor_id)
            conditions.append(
                or_(
                    AdminAuditLog.timestamp < cursor_ts,
                    and_(
                        AdminAuditLog.timestamp == cursor_ts,
                        AdminAuditLog.id < cursor_id,
                    ),
                )
            )

        effective_limit = min(limit, _PAGE_SIZE)
        stmt = (
            select(AdminAuditLog)
            .where(and_(*conditions) if conditions else True)
            .order_by(AdminAuditLog.timestamp.desc(), AdminAuditLog.id.desc())
            .limit(effective_limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
