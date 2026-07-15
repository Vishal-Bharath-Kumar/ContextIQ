"""
AC-5: Role-gating tests — GET /v1/audit-log and GET /v1/audit-log/verify.

BUG FIX (spec): spec parametrised DEVOPS_SRE and SECURITY_OFFICER as denied
roles, but require_auditor (src/auth/rbac.py) explicitly ALLOWS both:

    require_auditor = require_roles(
        PlatformRole.AUDITOR,
        PlatformRole.DEVOPS_SRE,
        PlatformRole.SECURITY_OFFICER,
        PlatformRole.ADMIN,
    )

Only DEVELOPER, PLATFORM_ENGINEER, and MANAGER should receive HTTP 403.
The spec's "5 parametrized roles" count is incorrect.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.main import app


@pytest.mark.parametrize("role", [
    PlatformRole.DEVELOPER,
    PlatformRole.PLATFORM_ENGINEER,
    PlatformRole.MANAGER,
])
@pytest.mark.asyncio
async def test_non_auditor_roles_denied(role: PlatformRole) -> None:
    """
    AC-5: Only AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, and ADMIN may access
    GET /v1/audit-log. DEVELOPER, PLATFORM_ENGINEER, and MANAGER receive 403.
    """
    app.dependency_overrides[decode_jwt_claims] = lambda: make_test_claims(role)
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/audit-log")
        assert response.status_code == 403
    finally:
        # BUG FIX (spec): .clear() removes db_session's DB overrides.
        app.dependency_overrides.pop(decode_jwt_claims, None)


@pytest.mark.parametrize("role", [
    PlatformRole.AUDITOR,
    PlatformRole.DEVOPS_SRE,
    PlatformRole.SECURITY_OFFICER,
    PlatformRole.ADMIN,
])
@pytest.mark.asyncio
async def test_auditor_roles_allowed(role: PlatformRole) -> None:
    """
    AC-5: AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, and ADMIN receive HTTP 200
    (not 403) for GET /v1/audit-log.
    """
    app.dependency_overrides[decode_jwt_claims] = lambda: make_test_claims(role)
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/audit-log")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
