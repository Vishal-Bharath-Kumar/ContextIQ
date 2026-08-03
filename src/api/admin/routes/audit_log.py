"""
GET /v1/audit-log — filtered, cursor-paginated audit log query endpoint.

AC-4: supports filter params user, action, resource_type, resource_id,
      date_from, date_to with keyset pagination via opaque cursor token.
AC-5: AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, or ADMIN role required
      (enforced by require_auditor which mirrors the frontend RequireAuditor guard).
AC-6: reads from the read replica (get_read_db) to keep reporting traffic
      off the primary write path.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# BUG FIX (spec): `from src.db.session import get_session` does not exist.
# Use get_read_db (read replica — AC-6) from src.data.dependencies.
from src.data.dependencies import get_read_db
from src.audit.admin_audit_log.models import AdminAuditLog
from src.audit.admin_audit_log.query_repository import (
    AuditLogQueryRepository,
    encode_cursor,
    _PAGE_SIZE,
)
from src.audit.admin_audit_log.schemas import AuditLogEntry
from src.audit.admin_audit_log.hash_chain import (
    compute_row_hash,
    GENESIS_PREV_HASH,
    row_fields_for_hashing,
)
from src.auth import require_auditor

router = APIRouter(prefix="/v1/audit-log", tags=["audit-log"])


class AuditLogListResponse(BaseModel):
    items:       list[AuditLogEntry]
    next_cursor: str | None   # opaque cursor token; None → no more pages


@router.get(
    "",
    response_model=AuditLogListResponse,
    dependencies=[Depends(require_auditor)],
    summary="Query audit log",
    description=(
        "AC-4: Filter by user, action, resource type, resource ID, and date range. "
        "Use `cursor` from the previous response to fetch subsequent pages."
    ),
)
async def list_audit_log(
    session: Annotated[AsyncSession, Depends(get_read_db)],
    actor_user_id: Annotated[str | None, Query(alias="user")] = None,
    action:        Annotated[str | None, Query()] = None,
    resource_type: Annotated[str | None, Query()] = None,
    resource_id:   Annotated[str | None, Query()] = None,
    date_from:     Annotated[datetime | None, Query()] = None,
    date_to:       Annotated[datetime | None, Query()] = None,
    cursor:        Annotated[str | None, Query()] = None,
    limit:         Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditLogListResponse:
    repo = AuditLogQueryRepository(session)
    rows = await repo.list_filtered(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )
    items = [
        AuditLogEntry(
            id=row.id,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            actor_user_id=row.actor_user_id,
            ip_address=row.ip_address,
            before_state=row.before_state,
            after_state=row.after_state,
            timestamp=row.timestamp,
            row_hash=row.row_hash,
        )
        for row in rows
    ]
    # BUG FIX (spec): compare against min(limit, _PAGE_SIZE) — the repo caps
    # internally at _PAGE_SIZE=50; len(rows) == limit would be False when
    # limit > 50, incorrectly returning next_cursor=None on a full page.
    effective_limit = min(limit, _PAGE_SIZE)
    next_cursor: str | None = (
        encode_cursor(rows[-1].timestamp, rows[-1].id)
        if len(rows) == effective_limit
        else None
    )
    return AuditLogListResponse(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# AC-6: Chain integrity verification endpoint
# ---------------------------------------------------------------------------

class IntegrityVerificationResult(BaseModel):
    total_rows:     int
    first_mismatch: int | None   # 1-based row index; None if chain is intact
    is_intact:      bool


@router.get(
    "/verify",
    response_model=IntegrityVerificationResult,
    dependencies=[Depends(require_auditor)],
    summary="Verify audit log chain integrity",
    description=(
        "AC-6: Re-computes SHA-256 chain hashes for every row in insertion order "
        "(timestamp ASC, id ASC) and reports the first mismatch, if any."
    ),
)
async def verify_audit_log_integrity(
    # BUG FIX (spec): `Depends(get_session)` does not exist.
    # Use get_read_db — this is a read-only full-table scan, so route it to
    # the replica to avoid load on the primary write path.
    session: Annotated[AsyncSession, Depends(get_read_db)],
) -> IntegrityVerificationResult:
    """
    Fetches ALL rows ordered by (timestamp ASC, id ASC) and re-derives the
    hash chain from GENESIS_PREV_HASH.  Returns the 1-based index of the
    first row where the recomputed hash diverges from the stored hash, or
    None if the entire chain is intact.

    Performance note: this scans the full table.  For very large audit logs
    a date-range parameter can be added in a future iteration.
    """
    result = await session.execute(
        select(AdminAuditLog).order_by(
            AdminAuditLog.timestamp.asc(),
            AdminAuditLog.id.asc(),
        )
    )
    rows = result.scalars().all()

    prev_hash = GENESIS_PREV_HASH
    first_mismatch: int | None = None

    for idx, row in enumerate(rows, start=1):
        fields = row_fields_for_hashing(
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            actor_user_id=row.actor_user_id,
            ip_address=row.ip_address,
            before_state=row.before_state,
            after_state=row.after_state,
            timestamp=row.timestamp,
        )
        expected = compute_row_hash(prev_hash, fields)
        if row.row_hash != expected:
            first_mismatch = idx
            break
        prev_hash = row.row_hash

    return IntegrityVerificationResult(
        total_rows=len(rows),
        first_mismatch=first_mismatch,
        is_intact=first_mismatch is None,
    )

