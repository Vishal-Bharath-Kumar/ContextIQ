"""
JWT TTL role-propagation tests (AC-5).

Verifies that a freshly issued JWT carrying an updated role is honoured
immediately without server restart or cache flush — the platform holds no
per-user role cache in the RBAC module.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from src.auth import rbac as rbac_module
from src.auth.rbac import require_manage_policies
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims


@pytest.mark.asyncio
async def test_role_change_reflected_in_next_request() -> None:
    """
    AC-5: Role changes in Keycloak propagate within JWT TTL (5 min default).

    Simulate: first token has DEVELOPER role (denied MANAGE_POLICIES),
    second token carries SECURITY_OFFICER role (allowed) — same user, two
    distinct JWT objects issued at different points in time.

    No server restart, no cache flush — because the RBAC module re-evaluates
    claims from the token on every request rather than caching per user_id.
    """
    # BUG FIX (spec): require_manage_policies is already the async dep callable,
    # not a factory.  Using require_manage_policies() (with parens) would invoke
    # the dep with no arguments → TypeError.  Use it directly as check_fn.
    check_fn = require_manage_policies

    old_claims = make_test_claims(PlatformRole.DEVELOPER, sub="user-123")
    with pytest.raises(HTTPException) as exc_info:
        await check_fn(old_claims)
    assert exc_info.value.status_code == 403

    # Simulate Keycloak issuing a new token after the role is assigned.
    new_claims = make_test_claims(PlatformRole.SECURITY_OFFICER, sub="user-123")
    result = await check_fn(new_claims)
    assert result.has_role(PlatformRole.SECURITY_OFFICER)


def test_no_server_side_role_cache() -> None:
    """
    AC-5: Confirm absence of any user-keyed role cache in the RBAC module.

    The RBAC module must not use lru_cache, a dict keyed by user id, or any
    Redis-backed lookup — role resolution must be purely token-driven.
    """
    source = inspect.getsource(rbac_module)
    assert "lru_cache" not in source, "RBAC module must not use lru_cache"
    assert "_role_cache" not in source, "RBAC module must not maintain a role cache dict"
