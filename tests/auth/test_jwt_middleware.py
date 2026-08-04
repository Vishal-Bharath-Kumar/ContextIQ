"""
JWT middleware integration tests — TASK-US043-05.

Verifies that JWTAuthMiddleware correctly enforces authentication on every
protected route and bypasses /healthz (AC-3, AC-6).

Tests are marked ``real_middleware`` so the autouse ``bypass_jwt_middleware``
fixture in conftest.py does NOT patch dispatch — the actual middleware runs.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from starlette.requests import Request
from httpx import ASGITransport, AsyncClient

from src.auth.jwks_client import JWKSClient
from src.main import create_app


@pytest.fixture
async def app_with_mock_jwks(
    keycloak_settings: Any,
    jwks_payload: dict[str, Any],
) -> AsyncGenerator[FastAPI, None]:
    """
    BUG FIX (spec — 2 bugs):

    1. The spec's fixture was synchronous and could not ``await client.startup()``,
       so the JWKSClient was never started → AssertionError on first decode.
       Fixed: async fixture that awaits ``client.startup()`` inside a respx mock.

    2. The spec defined a local ``lifespan()`` coroutine but never passed it to
       the app — the lifespan was dead code.
       Fixed: pass the pre-started client to ``create_app(jwks_client=client)``.
       The factory's lifespan honours the externally-managed lifecycle flag and
       does NOT call startup/shutdown again.

    The respx mock is only needed during ``startup()`` (which pre-warms the JWKS
    cache).  Decode calls during the test use the in-memory cache (TTL = 300 s).
    """
    with respx.mock(assert_all_called=False) as _mock:
        _mock.get(keycloak_settings.jwks_uri).mock(
            return_value=httpx.Response(200, json=jwks_payload)
        )
        client = JWKSClient(keycloak_settings)
        await client.startup()   # pre-warms cache via mock

    # Mock context closed; keys are cached for 300 s — no more HTTP fetches.
    app = create_app(jwks_client=client)
    yield app
    await client.shutdown()


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------


@pytest.mark.real_middleware
async def test_missing_auth_header_returns_401(app_with_mock_jwks: FastAPI) -> None:
    """AC-3: Requests with no Authorization header on a protected path return 401."""
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get("/v1/models")
    assert response.status_code == 401


@pytest.mark.real_middleware
async def test_missing_auth_header_on_mcp_returns_oauth_challenge(
    app_with_mock_jwks: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get("/mcp")

    assert response.status_code == 401
    assert "www-authenticate" in response.headers
    challenge = response.headers["www-authenticate"]
    assert 'realm="contextiq-mcp"' in challenge
    assert 'resource_metadata="http://test/.well-known/oauth-protected-resource"' in challenge


@pytest.mark.real_middleware
async def test_oauth_protected_resource_metadata_is_public(
    app_with_mock_jwks: FastAPI,
    keycloak_settings: Any,
) -> None:
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "http://test/mcp",
        "authorization_servers": [keycloak_settings.public_issuer],
    }


@pytest.mark.real_middleware
async def test_valid_token_passes_middleware(
    app_with_mock_jwks: FastAPI,
    mint_token: Any,
) -> None:
    """AC-3: Valid RS256 token lets the request through (middleware does not 401)."""
    token = mint_token(roles=["platform_engineer"])
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
    # 200 (OK) or 403 (RBAC denied) — both confirm middleware passed the token
    assert response.status_code != 401


@pytest.mark.real_middleware
async def test_expired_token_returns_401(
    app_with_mock_jwks: FastAPI,
    mint_token: Any,
) -> None:
    """AC-6: Expired access token (exp in the past) returns HTTP 401."""
    token = mint_token(roles=["admin"], exp_offset=-1)
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 401


@pytest.mark.real_middleware
async def test_health_endpoint_skips_auth(app_with_mock_jwks: FastAPI) -> None:
    """/healthz is in _SKIP_PATHS and must return 200 with no Authorization header."""
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200


def test_create_app_includes_request_context_middleware() -> None:
    app = create_app(jwks_client=None)
    middleware_names = [entry.cls.__name__ for entry in app.user_middleware]
    assert "RequestContextMiddleware" in middleware_names


@pytest.mark.real_middleware
async def test_valid_token_populates_request_state_identity(
    app_with_mock_jwks: FastAPI,
    mint_token: Any,
) -> None:
    observed: dict[str, Any] = {}

    @app_with_mock_jwks.get("/_identity-check")
    async def _identity_check(request: Request) -> dict[str, str | None]:
        observed["user_id"] = getattr(request.state, "user_id", None)
        observed["session_id"] = getattr(request.state, "session_id", None)
        claims = getattr(request.state, "jwt_claims", None)
        observed["sub"] = getattr(claims, "sub", None)
        return observed

    token = mint_token(roles=["admin"])
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get(
            "/_identity-check",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == body["sub"]
    assert body["session_id"]
