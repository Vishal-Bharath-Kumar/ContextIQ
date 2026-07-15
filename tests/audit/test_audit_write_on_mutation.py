"""
AC-1: Row written for each mutating route.

Verifies that POST /v1/policies and PATCH /v1/models/{id}/status each
produce exactly one admin_audit_log row with the correct field values.

ADMIN claims are used so that both MANAGE_POLICIES and MANAGE_MODELS
permission checks pass.

BUG FIX (spec): spec used PlatformRole.PLATFORM_ENGINEER which lacks
MANAGE_POLICIES (only SECURITY_OFFICER / ADMIN have it) — POST /v1/policies
would return 403, not 201.  ADMIN bypasses all permission checks.

BUG FIX (spec): spec called app.dependency_overrides.clear() in cleanup which
also removes get_db / get_read_db overrides set by the db_session fixture,
causing subsequent DB queries in the same test to fail.  Use .pop() instead.
"""
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.models import AdminAuditLog
from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.main import app

# BUG FIX (spec): PLATFORM_ENGINEER lacks MANAGE_POLICIES —
# POST /v1/policies would return 403, not 201.  Use ADMIN instead.
_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN)


@pytest.fixture(autouse=True)
def inject_admin_claims() -> None:
    """Inject ADMIN claims so all mutating routes in this module pass RBAC."""
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    yield
    # BUG FIX (spec): .clear() removes db_session's get_db / get_read_db overrides.
    # Use .pop() to remove only the claim override.
    app.dependency_overrides.pop(decode_jwt_claims, None)


@pytest.mark.asyncio
async def test_create_policy_writes_audit_row(
    db_session: AsyncSession,
    mock_policy_create: Any,
) -> None:
    """AC-1: POST /v1/policies creates exactly one admin_audit_log row."""
    before = await db_session.scalar(
        select(func.count()).select_from(AdminAuditLog)
    )

    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/policies",
            json={"name": "test-policy", "rego": "package test\ndefault allow = false"},
            headers={"Authorization": "Bearer mock"},
        )

    assert response.status_code == 201

    after = await db_session.scalar(
        select(func.count()).select_from(AdminAuditLog)
    )
    assert after == before + 1

    row = await db_session.scalar(
        select(AdminAuditLog)
        .order_by(AdminAuditLog.timestamp.desc())
        .limit(1)
    )
    assert row is not None
    assert row.action        == "policy.created"
    assert row.resource_type == "policy"
    assert row.actor_user_id == _ADMIN_CLAIMS.sub
    assert row.ip_address    != ""
    assert row.before_state  is None          # create: no before state
    assert row.after_state   is not None      # create: after state populated


@pytest.mark.asyncio
async def test_update_model_status_writes_audit_row(
    db_session: AsyncSession,
    seed_model: Any,
) -> None:
    """AC-1: PATCH /v1/models/{id}/status creates one audit row with before/after state."""
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/v1/models/{seed_model.id}/status",
            json={"active": False},
            headers={"Authorization": "Bearer mock"},
        )

    assert response.status_code == 200

    row = await db_session.scalar(
        select(AdminAuditLog)
        .where(AdminAuditLog.resource_id == str(seed_model.id))
        .order_by(AdminAuditLog.timestamp.desc())
        .limit(1)
    )
    assert row is not None
    assert row.action       == "model.status_changed"
    assert row.before_state is not None
    assert row.after_state  is not None
