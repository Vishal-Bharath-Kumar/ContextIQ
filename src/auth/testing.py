"""
Test helper for constructing JWTClaims without JWT signature verification.

FOR UNIT TESTS ONLY — must not be imported in production application code.
"""
from __future__ import annotations

import time

from src.auth.roles import PlatformRole
from src.gateway.schemas.auth_types import JWTClaims


def make_test_claims(
    *roles: PlatformRole,
    sub: str = "test-user-id",
) -> JWTClaims:
    """
    Build a JWTClaims instance with the given roles for unit testing.

    Populates all required fields with safe defaults so tests only need to
    specify the roles under test.  No JWT signature verification is performed.

    Example::

        claims = make_test_claims(PlatformRole.AUDITOR)
        assert claims.has_permission(Permission.READ_TRACES)
    """
    now = int(time.time())
    return JWTClaims(
        sub=sub,
        iss="https://keycloak.test/realms/contextiq",
        exp=now + 3600,
        iat=now,
        email="testuser@example.com",
        email_verified=True,
        preferred_username="testuser",
        realm_access={"roles": [r.value for r in roles]},
        resource_access={},
    )
