"""
Unit tests for TASK-US004-03: JWT Claims Extraction and RequestContext Population.

Coverage targets (≥ 90%):
  - JWTClaims.roles: realm-only, client-only, merged from both, empty
  - JWTClaims.roles: returns frozenset (immutable)
  - Unknown roles emit WARNING log via _warn_unknown_roles
  - RequestContext fields: user_id == sub, username == preferred_username,
      roles == frozenset(claims.roles), frozen=True
  - JWTAuthMiddleware binds RequestContext via set_request_context after verify
  - get_request_context() returns the bound context without re-parsing the JWT
"""
from __future__ import annotations

import logging
from contextvars import copy_context
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gateway.context.request_context import (
    RequestContext,
    get_request_context,
    set_request_context,
    _request_ctx,
)
from src.gateway.middleware.jwt_auth import (
    JWTAuthMiddleware,
    _warn_unknown_roles,
    _KNOWN_ROLES,
)
from src.gateway.schemas.auth_types import JWTClaims
from src.auth.roles import Permission, PlatformRole


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_claims(**overrides: Any) -> JWTClaims:
    defaults: dict[str, Any] = {
        "sub": "user-uuid-001",
        "iss": "http://keycloak/realms/contextiq",
        "exp": 9999999999,
        "iat": 1700000000,
        "preferred_username": "alice",
        "email": "alice@example.com",
        "realm_access": {},
        "resource_access": {},
    }
    defaults.update(overrides)
    return JWTClaims(**defaults)


def _make_scope(
    path: str = "/mcp",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> dict[str, Any]:
    return {
        "type": "http",
        "path": path,
        "headers": headers or [(b"authorization", b"Bearer test.token.here")],
        "query_string": query_string,
    }


# ---------------------------------------------------------------------------
# JWTClaims.roles — realm_access
# ---------------------------------------------------------------------------

class TestJWTClaimsRoles:
    def test_realm_roles_only(self) -> None:
        claims = _make_claims(realm_access={"roles": ["developer", "auditor"]})
        assert claims.roles == frozenset({"developer", "auditor"})

    def test_client_roles_only(self) -> None:
        claims = _make_claims(
            resource_access={"contextiq-gateway": {"roles": ["admin"]}}
        )
        assert claims.roles == frozenset({"admin"})

    def test_merged_realm_and_client_roles(self) -> None:
        claims = _make_claims(
            realm_access={"roles": ["developer"]},
            resource_access={
                "contextiq-gateway": {"roles": ["platform_engineer"]},
                "another-client": {"roles": ["manager"]},
            },
        )
        assert claims.roles == frozenset({"developer", "platform_engineer", "manager"})

    def test_empty_roles(self) -> None:
        claims = _make_claims(realm_access={}, resource_access={})
        assert claims.roles == frozenset()

    def test_roles_returns_frozenset(self) -> None:
        claims = _make_claims(realm_access={"roles": ["developer"]})
        result = claims.roles
        assert isinstance(result, frozenset)

    def test_duplicate_roles_deduplicated(self) -> None:
        claims = _make_claims(
            realm_access={"roles": ["developer"]},
            resource_access={"client": {"roles": ["developer"]}},
        )
        assert claims.roles == frozenset({"developer"})

    def test_realm_access_missing_roles_key(self) -> None:
        claims = _make_claims(realm_access={"other_key": ["something"]})
        assert claims.roles == frozenset()

    def test_resource_access_missing_roles_key(self) -> None:
        claims = _make_claims(
            resource_access={"some-client": {"other_key": ["something"]}}
        )
        assert claims.roles == frozenset()


# ---------------------------------------------------------------------------
# JWTClaims.has_role / has_any_role / has_permission
# ---------------------------------------------------------------------------

class TestJWTClaimsHasRole:
    def test_has_role_true_exact_match(self) -> None:
        claims = _make_claims(realm_access={"roles": ["developer"]})
        assert claims.has_role(PlatformRole.DEVELOPER) is True

    def test_has_role_false_missing(self) -> None:
        claims = _make_claims(realm_access={"roles": ["developer"]})
        assert claims.has_role(PlatformRole.ADMIN) is False

    def test_has_role_case_insensitive(self) -> None:
        claims = _make_claims(realm_access={"roles": ["ADMIN"]})
        assert claims.has_role(PlatformRole.ADMIN) is True

    def test_has_any_role_returns_true_on_first_match(self) -> None:
        claims = _make_claims(realm_access={"roles": ["manager"]})
        assert claims.has_any_role(PlatformRole.ADMIN, PlatformRole.MANAGER) is True

    def test_has_any_role_returns_false_when_none_match(self) -> None:
        claims = _make_claims(realm_access={"roles": ["auditor"]})
        assert claims.has_any_role(PlatformRole.ADMIN, PlatformRole.DEVELOPER) is False

    def test_has_permission_admin_bypasses_matrix(self) -> None:
        claims = _make_claims(realm_access={"roles": ["admin"]})
        assert claims.has_permission(Permission.MANAGE_CONNECTORS) is True

    def test_has_permission_role_in_matrix(self) -> None:
        claims = _make_claims(realm_access={"roles": ["developer"]})
        assert claims.has_permission(Permission.CALL_CONTEXT_TOOLS) is True

    def test_has_permission_role_not_in_matrix(self) -> None:
        claims = _make_claims(realm_access={"roles": ["auditor"]})
        assert claims.has_permission(Permission.MANAGE_CONNECTORS) is False


# ---------------------------------------------------------------------------
# RequestContext — immutability and fields
# ---------------------------------------------------------------------------

class TestRequestContext:
    def _make_ctx(self, **overrides: Any) -> RequestContext:
        defaults: dict[str, Any] = {
            "request_id": "req-001",
            "user_id": "user-uuid-001",
            "username": "alice",
            "roles": frozenset({"developer"}),
            "session_id": "sess-abc",
            "trace_id": 0,
        }
        defaults.update(overrides)
        return RequestContext(**defaults)

    def test_user_id_equals_sub(self) -> None:
        ctx = self._make_ctx(user_id="sub-value-xyz")
        assert ctx.user_id == "sub-value-xyz"

    def test_username_field_set(self) -> None:
        ctx = self._make_ctx(username="alice")
        assert ctx.username == "alice"

    def test_roles_is_frozenset(self) -> None:
        ctx = self._make_ctx(roles=frozenset({"admin", "developer"}))
        assert isinstance(ctx.roles, frozenset)
        assert ctx.roles == frozenset({"admin", "developer"})

    def test_frozen_immutable(self) -> None:
        ctx = self._make_ctx()
        with pytest.raises((FrozenInstanceError, AttributeError)):
            ctx.user_id = "hacked"  # type: ignore[misc]

    def test_empty_roles_allowed(self) -> None:
        ctx = self._make_ctx(roles=frozenset())
        assert ctx.roles == frozenset()

    def test_username_empty_string_allowed(self) -> None:
        ctx = self._make_ctx(username="")
        assert ctx.username == ""


# ---------------------------------------------------------------------------
# _warn_unknown_roles helper
# ---------------------------------------------------------------------------

class TestWarnUnknownRoles:
    def test_no_warning_for_known_roles(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.gateway.middleware.jwt_auth"):
            _warn_unknown_roles(frozenset({"developer", "admin"}), "/mcp")
        assert not caplog.records

    def test_warning_for_unknown_role(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.gateway.middleware.jwt_auth"):
            _warn_unknown_roles(frozenset({"super_admin"}), "/mcp")
        assert len(caplog.records) == 1
        assert "unknown roles" in caplog.records[0].message
        assert "super_admin" in caplog.records[0].message

    def test_warning_includes_path(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.gateway.middleware.jwt_auth"):
            _warn_unknown_roles(frozenset({"ghost_role"}), "/v1/tools")
        assert "/v1/tools" in caplog.records[0].message

    def test_no_warning_for_empty_roles(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.gateway.middleware.jwt_auth"):
            _warn_unknown_roles(frozenset(), "/mcp")
        assert not caplog.records

    def test_case_insensitive_known_check(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.gateway.middleware.jwt_auth"):
            _warn_unknown_roles(frozenset({"DEVELOPER", "ADMIN"}), "/mcp")
        assert not caplog.records

    def test_mixed_known_and_unknown_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.gateway.middleware.jwt_auth"):
            _warn_unknown_roles(frozenset({"developer", "secret_role"}), "/mcp")
        assert len(caplog.records) == 1
        assert "secret_role" in caplog.records[0].message


# ---------------------------------------------------------------------------
# _KNOWN_ROLES constant
# ---------------------------------------------------------------------------

class TestKnownRoles:
    def test_contains_all_platform_roles(self) -> None:
        expected = {
            "developer",
            "platform_engineer",
            "devops_sre",
            "admin",
            "security_officer",
            "manager",
            "auditor",
        }
        assert expected == _KNOWN_ROLES


# ---------------------------------------------------------------------------
# set_request_context / get_request_context isolation
# ---------------------------------------------------------------------------

class TestRequestContextVar:
    def test_set_and_get(self) -> None:
        ctx = RequestContext(
            request_id="r1",
            user_id="u1",
            username="bob",
            roles=frozenset({"developer"}),
            session_id="s1",
            trace_id=0,
        )
        token = set_request_context(ctx)
        try:
            assert get_request_context() is ctx
        finally:
            _request_ctx.reset(token)

    def test_lookup_error_when_not_set(self) -> None:
        def _check() -> None:
            with pytest.raises(LookupError):
                get_request_context()

        copy_context().run(_check)

    def test_context_isolated_between_tasks(self) -> None:
        ctx_a = RequestContext(
            request_id="r-a",
            user_id="ua",
            username="alice",
            roles=frozenset({"admin"}),
            session_id="sa",
            trace_id=0,
        )
        ctx_b = RequestContext(
            request_id="r-b",
            user_id="ub",
            username="bob",
            roles=frozenset({"developer"}),
            session_id="sb",
            trace_id=0,
        )

        results: dict[str, str] = {}

        def _run_a() -> None:
            token = set_request_context(ctx_a)
            try:
                results["a"] = get_request_context().user_id
            finally:
                _request_ctx.reset(token)

        def _run_b() -> None:
            token = set_request_context(ctx_b)
            try:
                results["b"] = get_request_context().user_id
            finally:
                _request_ctx.reset(token)

        copy_context().run(_run_a)
        copy_context().run(_run_b)
        assert results["a"] == "ua"
        assert results["b"] == "ub"


# ---------------------------------------------------------------------------
# JWTAuthMiddleware — RequestContext binding integration
# ---------------------------------------------------------------------------

class TestJWTAuthMiddlewareContextBinding:
    """Verify that JWTAuthMiddleware binds RequestContext after verify()."""

    def _make_valid_claims(self, **overrides: Any) -> JWTClaims:
        return _make_claims(**overrides)

    async def _call_middleware(
        self,
        claims: JWTClaims,
        path: str = "/mcp",
    ) -> RequestContext | None:
        """
        Run JWTAuthMiddleware with a mocked JWKS client that returns *claims*.
        Captures the RequestContext visible inside the inner app.
        """
        captured: dict[str, Any] = {}

        async def inner_app(
            scope: dict[str, Any], receive: Any, send: Any
        ) -> None:
            captured["ctx"] = get_request_context()

        jwks_mock = MagicMock()
        jwks_mock.verify = AsyncMock(return_value=claims)

        middleware = JWTAuthMiddleware(inner_app, jwks_mock)

        scope = _make_scope(path=path)
        await middleware(scope, AsyncMock(), AsyncMock())
        return captured.get("ctx")

    @pytest.mark.asyncio
    async def test_user_id_equals_sub(self) -> None:
        claims = self._make_valid_claims()
        ctx = await self._call_middleware(claims)
        assert ctx is not None
        assert ctx.user_id == claims.sub

    @pytest.mark.asyncio
    async def test_username_equals_preferred_username(self) -> None:
        claims = self._make_valid_claims(preferred_username="alice")
        ctx = await self._call_middleware(claims)
        assert ctx is not None
        assert ctx.username == "alice"

    @pytest.mark.asyncio
    async def test_username_empty_when_claim_absent(self) -> None:
        claims = self._make_valid_claims(preferred_username=None)
        ctx = await self._call_middleware(claims)
        assert ctx is not None
        assert ctx.username == ""

    @pytest.mark.asyncio
    async def test_roles_frozenset_from_realm_access(self) -> None:
        claims = self._make_valid_claims(
            realm_access={"roles": ["developer", "auditor"]},
        )
        ctx = await self._call_middleware(claims)
        assert ctx is not None
        assert ctx.roles == frozenset({"developer", "auditor"})

    @pytest.mark.asyncio
    async def test_roles_merged_from_both_sources(self) -> None:
        claims = self._make_valid_claims(
            realm_access={"roles": ["developer"]},
            resource_access={"contextiq-gateway": {"roles": ["platform_engineer"]}},
        )
        ctx = await self._call_middleware(claims)
        assert ctx is not None
        assert "developer" in ctx.roles
        assert "platform_engineer" in ctx.roles

    @pytest.mark.asyncio
    async def test_empty_roles_not_error(self) -> None:
        claims = self._make_valid_claims(realm_access={}, resource_access={})
        ctx = await self._call_middleware(claims)
        assert ctx is not None
        assert ctx.roles == frozenset()

    @pytest.mark.asyncio
    async def test_context_reset_after_request(self) -> None:
        """RequestContext must not leak to subsequent requests."""
        claims = self._make_valid_claims()
        await self._call_middleware(claims)

        # After middleware completes the context should no longer be set in
        # the current task (it was reset in the finally block).
        with pytest.raises(LookupError):
            get_request_context()

    @pytest.mark.asyncio
    async def test_unknown_roles_emit_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        claims = self._make_valid_claims(
            realm_access={"roles": ["ghost_role"]},
        )
        with caplog.at_level(logging.WARNING, logger="src.gateway.middleware.jwt_auth"):
            await self._call_middleware(claims)
        assert any("unknown roles" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_context_accessible_without_jwt_reparse(self) -> None:
        """
        Downstream handlers must retrieve user identity via get_request_context()
        without any additional JWT parsing (no verify() or decode() calls inside
        the inner app).
        """
        claims = self._make_valid_claims(preferred_username="charlie")
        captured: dict[str, Any] = {}
        parse_count = {"n": 0}

        async def inner_app(
            scope: dict[str, Any], receive: Any, send: Any
        ) -> None:
            ctx = get_request_context()
            captured["username"] = ctx.username
            captured["user_id"] = ctx.user_id
            # Confirm no re-parsing happened (parse_count unchanged after bind)
            captured["parses_inside_handler"] = parse_count["n"]

        jwks_mock = MagicMock()

        async def _verify(token: str) -> JWTClaims:
            parse_count["n"] += 1
            return claims

        jwks_mock.verify = _verify

        middleware = JWTAuthMiddleware(inner_app, jwks_mock)
        scope = _make_scope()
        await middleware(scope, AsyncMock(), AsyncMock())

        assert captured["username"] == "charlie"
        assert captured["user_id"] == claims.sub
        # verify() called exactly once (by middleware), zero times inside handler
        assert captured["parses_inside_handler"] == 1
