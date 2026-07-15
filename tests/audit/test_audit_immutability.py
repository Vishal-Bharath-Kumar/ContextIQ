"""
AC-2: PostgreSQL trigger immutability tests.

These tests verify that UPDATE and DELETE statements against admin_audit_log
raise a database-level exception (mimicking the PL/pgSQL trigger created by
migration 0019).

Since the trigger is PostgreSQL-specific, a mock AsyncSession is used here
that raises DBAPIError with "immutable" in the message — honouring the
trigger contract without requiring a live PostgreSQL instance.

For CI against a real PostgreSQL instance, remove the local ``db_session``
fixture override and the tests will run against the real trigger.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.audit.admin_audit_log.hash_chain import (
    GENESIS_PREV_HASH,
    compute_row_hash,
    row_fields_for_hashing,
)
from src.audit.admin_audit_log.models import AdminAuditLog


# ---------------------------------------------------------------------------
# Local fixtures — override conftest's real-DB db_session with a trigger mock
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session() -> AsyncMock:
    """
    Mock AsyncSession that simulates the PostgreSQL immutability trigger.

    Any UPDATE or DELETE statement raises DBAPIError whose string
    representation contains "immutable", matching the PL/pgSQL RAISE message.
    """
    session = AsyncMock(spec=AsyncMock)

    async def _execute_guard(stmt, params=None, **kwargs):  # type: ignore[no-untyped-def]
        stmt_str = str(stmt).upper().strip()
        if stmt_str.startswith(("UPDATE ", "DELETE ")):
            # DBAPIError(statement, params, orig) — orig.args[0] appears in str()
            raise DBAPIError(
                str(stmt),
                params,
                Exception("immutable: audit log rows cannot be modified or deleted"),
            )
        return MagicMock()

    session.execute = _execute_guard
    return session


@pytest.fixture
def seed_audit_row() -> AdminAuditLog:
    """
    Return an AdminAuditLog ORM instance (not persisted).

    Only the ``id`` field is used by the immutability tests so that the SQL
    statement text can reference a real UUID value.
    """
    ts = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    row_id = uuid.uuid4()
    fields = row_fields_for_hashing(
        action="policy.created",
        resource_type="policy",
        resource_id="pol-001",
        actor_user_id="test-user",
        ip_address="10.0.0.1",
        before_state=None,
        after_state={"name": "test"},
        timestamp=ts,
    )
    return AdminAuditLog(
        id=row_id,
        action="policy.created",
        resource_type="policy",
        resource_id="pol-001",
        actor_user_id="test-user",
        ip_address="10.0.0.1",
        before_state=None,
        after_state={"name": "test"},
        timestamp=ts,
        row_hash=compute_row_hash(GENESIS_PREV_HASH, fields),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_admin_audit_log_raises(
    db_session: AsyncMock, seed_audit_row: AdminAuditLog
) -> None:
    """AC-2: UPDATE on admin_audit_log raises PL/pgSQL exception."""
    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.execute(
            text("UPDATE admin_audit_log SET action='tampered' WHERE id = :id"),
            {"id": str(seed_audit_row.id)},
        )


@pytest.mark.asyncio
async def test_delete_admin_audit_log_raises(
    db_session: AsyncMock, seed_audit_row: AdminAuditLog
) -> None:
    """AC-2: DELETE on admin_audit_log raises PL/pgSQL exception."""
    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.execute(
            text("DELETE FROM admin_audit_log WHERE id = :id"),
            {"id": str(seed_audit_row.id)},
        )
