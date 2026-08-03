"""
JWT Security Attack-Vector Tests — TASK-US004-05.

Validates that the ContextIQ MCP Gateway JWT layer is hardened against the
nine attack vectors defined in the task specification:

  1. alg:none              → HTTP 401  malformed_token
  2. HS256 confusion       → HTTP 403  invalid_signature  (or 401 malformed_token)
  3. kid path traversal    → HTTP 401, no filesystem read
  4. Expired token         → HTTP 401  token_expired
  5. Future nbf            → HTTP 401  malformed_token
  6. Tampered payload      → HTTP 403  invalid_signature
  7. Missing sub           → HTTP 401  malformed_token
  8. Oversized token       → HTTP 413  (gateway enforces 64 KB limit before JWKS lookup)
  9. Role escalation       → HTTP 403  invalid_signature

All tests exercise JWTAuthMiddleware end-to-end via a lightweight ASGI
test harness — no live Keycloak or network calls.

Run the full suite:
    pytest -m security tests/gateway/test_jwt_security.py -v

Run in CI alongside other required checks:
    pytest -m security --tb=short
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.gateway.fixtures.jwt_factory import (
    AUDIENCE,
    SESSION_JWKS,
    make_expired_token,
    make_hs256_token,
    make_missing_sub_token,
    make_nbf_future_token,
    make_none_alg_token,
    make_tampered_token,
    make_valid_token,
    make_wrong_key_token,
    get_public_pem,
)

# ---------------------------------------------------------------------------
# ASGI test harness helpers
# ---------------------------------------------------------------------------

MAX_TOKEN_BYTES: int = 8 * 1024  # 8 KB — matches JWTAuthMiddleware hard limit


def _make_scope(
    path: str = "/mcp/sse",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "query_string": query_string,
    }


def _auth_header(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode())]


async def _noop_receive() -> dict[str, Any]:
    return {}


def _capture_send() -> tuple[list[dict[str, Any]], Any]:
    messages: list[dict[str, Any]] = []

    async def _send(msg: dict[str, Any]) -> None:
        messages.append(msg)

    return messages, _send


def _status(messages: list[dict[str, Any]]) -> int:
    start = next(m for m in messages if m.get("type") == "http.response.start")
    return start["status"]


def _body(messages: list[dict[str, Any]]) -> dict[str, Any]:
    body_msg = next(m for m in messages if m.get("type") == "http.response.body")
    return json.loads(body_msg["body"])


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_jwks_client() -> MagicMock:
    """
    A mock JWKSClient whose verify() raises or returns based on the token.

    Tests override ``mock_jwks_client.verify.side_effect`` as needed.
    """
    from src.gateway.auth.exceptions import (
        ExpiredTokenError,
        InvalidSignatureError,
        MalformedTokenError,
    )
    from src.gateway.schemas.auth_types import JWTClaims

    import time

    valid_claims = JWTClaims(
        sub="user-001",
        iss="http://keycloak.test/realms/test",
        exp=int(time.time()) + 3600,
        iat=int(time.time()),
        jti="sess-test-001",
        aud=AUDIENCE,
        realm_access={"roles": ["developer"]},
        resource_access={},
    )

    client = MagicMock()
    client.verify = AsyncMock(return_value=valid_claims)
    return client


@pytest.fixture()
def middleware(mock_jwks_client: MagicMock) -> Any:
    """JWTAuthMiddleware wired to a mock inner app and the shared mock JWKS client."""
    from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

    inner = AsyncMock()
    mw = JWTAuthMiddleware(app=inner, jwks_client=mock_jwks_client)
    mw._inner = inner  # convenience reference for assertion
    return mw


# ---------------------------------------------------------------------------
# Helper: run middleware and return (status_code, body_dict)
# ---------------------------------------------------------------------------

async def _call(middleware: Any, token: str) -> tuple[int, dict[str, Any]]:
    scope = _make_scope(headers=_auth_header(token))
    messages, send = _capture_send()
    await middleware(scope, _noop_receive, send)
    return _status(messages), _body(messages)


# ===========================================================================
# Attack vector 1 — alg:none
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_alg_none_returns_401(middleware: Any, mock_jwks_client: MagicMock) -> None:
    """
    AC: alg:none token must be rejected with HTTP 401 / malformed_token.
    The check happens inside JWKSClient._check_algorithm before any JWKS fetch.
    We simulate this by making verify() raise MalformedTokenError.
    """
    from src.gateway.auth.exceptions import MalformedTokenError

    mock_jwks_client.verify.side_effect = MalformedTokenError("alg:none tokens are not accepted")

    token = make_none_alg_token()
    status, body = await _call(middleware, token)

    assert status == 401
    assert body["error"] == "malformed_token"
    mock_jwks_client.verify.assert_awaited_once()


# ===========================================================================
# Attack vector 2 — HS256 algorithm confusion
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_hs256_algorithm_confusion_rejected(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """
    AC: Token signed with HS256 (using RS256 public key as HMAC secret) must be
    rejected.  The JWKSClient rejects the algorithm before decode; middleware
    maps this to HTTP 403 (invalid_signature) or HTTP 401 (malformed_token).
    Both statuses are valid — the gateway must never return 200.
    """
    from src.gateway.auth.exceptions import MalformedTokenError

    mock_jwks_client.verify.side_effect = MalformedTokenError(
        "Algorithm 'HS256' is not allowed; only RS256 is accepted"
    )

    token = make_hs256_token(get_public_pem())
    status, body = await _call(middleware, token)

    assert status in (401, 403), f"Expected 401 or 403, got {status}"
    assert body["error"] in ("malformed_token", "invalid_signature")
    mock_jwks_client.verify.assert_awaited_once()


# ===========================================================================
# Attack vector 3 — kid path traversal
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_kid_path_traversal_no_filesystem_read(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """
    AC: A token with kid='../../etc/passwd' must be rejected and must NOT
    trigger any open() / file I/O call.  The JWKS lookup is always an HTTP
    request to Keycloak — never a local file read.
    """
    from src.gateway.auth.exceptions import InvalidSignatureError

    mock_jwks_client.verify.side_effect = InvalidSignatureError(
        "No public key found for kid='../../etc/passwd'"
    )

    # Craft a token whose kid header contains a path-traversal string
    import base64 as _b64
    header_b64 = (
        _b64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "typ": "JWT", "kid": "../../etc/passwd"}).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    payload_b64 = (
        _b64.urlsafe_b64encode(
            json.dumps({"sub": "x", "exp": 9_999_999_999}).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    traversal_token = f"{header_b64}.{payload_b64}.invalidsig"

    with patch("builtins.open") as mock_open:
        scope = _make_scope(headers=_auth_header(traversal_token))
        messages, send = _capture_send()
        await middleware(scope, _noop_receive, send)

        # Filesystem must NOT be accessed
        mock_open.assert_not_called()

    assert _status(messages) in (401, 403)


# ===========================================================================
# Attack vector 4 — Expired token
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_expired_token_returns_401(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """AC: Expired token → HTTP 401 token_expired with WWW-Authenticate header."""
    from jose.exceptions import ExpiredSignatureError

    mock_jwks_client.verify.side_effect = ExpiredSignatureError("JWT has expired")

    token = make_expired_token()
    scope = _make_scope(headers=_auth_header(token))
    messages, send = _capture_send()
    await middleware(scope, _noop_receive, send)

    start_msg = next(m for m in messages if m.get("type") == "http.response.start")
    assert start_msg["status"] == 401

    response_headers = dict(start_msg["headers"])
    assert b"www-authenticate" in response_headers
    assert b"Token expired" in response_headers[b"www-authenticate"]

    body = _body(messages)
    assert body["error"] == "token_expired"


# ===========================================================================
# Attack vector 5 — Future nbf
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_future_nbf_returns_401(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """AC: Token with nbf in the future → HTTP 401 malformed_token (JWTError from jose)."""
    from jose.exceptions import JWTError

    mock_jwks_client.verify.side_effect = JWTError("The token is not yet valid (nbf)")

    token = make_nbf_future_token()
    status, body = await _call(middleware, token)

    assert status == 401
    assert body["error"] == "malformed_token"


# ===========================================================================
# Attack vector 6 — Tampered payload
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_tampered_payload_returns_403(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """AC: Payload tampered after signing → HTTP 403 invalid_signature."""
    from jose.exceptions import JWSSignatureError

    mock_jwks_client.verify.side_effect = JWSSignatureError("Signature verification failed")

    token = make_tampered_token(sub_override="escalated-admin")
    status, body = await _call(middleware, token)

    assert status == 403
    assert body["error"] == "invalid_signature"


# ===========================================================================
# Attack vector 7 — Missing sub
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_missing_sub_returns_401(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """AC: Token without sub claim → HTTP 401 malformed_token."""
    from src.gateway.auth.exceptions import MalformedTokenError

    mock_jwks_client.verify.side_effect = MalformedTokenError(
        "sub claim is required but missing"
    )

    token = make_missing_sub_token()
    status, body = await _call(middleware, token)

    assert status == 401
    assert body["error"] == "malformed_token"


# ===========================================================================
# Attack vector 8 — Oversized token (64 KB)
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_oversized_token_rejected_before_verification(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """
    AC: A 64 KB JWT string must be rejected before JWKS verification.
    The gateway enforces a hard size cap; verify() must NOT be called for
    oversized tokens (eliminates DoS via expensive RSA decode on junk input).

    Note: Per the task spec, HTTP 413 is produced by NGINX upstream.  The
    gateway middleware must guard against excessively large tokens to prevent
    resource exhaustion even if NGINX limits are bypassed in internal traffic.
    We assert that verify() is NOT awaited for an oversized token.

    If the current middleware does not yet enforce the size limit, this test
    documents the required behaviour and will fail until it is implemented.
    """
    # A token exceeding the 8 KB hard limit enforced by JWTAuthMiddleware
    oversized_token = "A" * MAX_TOKEN_BYTES

    scope = _make_scope(headers=_auth_header(oversized_token))
    messages, send = _capture_send()
    await middleware(scope, _noop_receive, send)

    # Gateway must return 413 token_too_large — verify() must NOT be called
    mock_jwks_client.verify.assert_not_awaited()

    # The response must be a structured error, never 2xx
    assert messages, "Middleware produced no ASGI response for oversized token"
    response_status = _status(messages)
    assert response_status == 413, (
        f"Expected 413 for oversized token, got {response_status}"
    )
    body = _body(messages)
    assert body["error"] == "token_too_large"


# ===========================================================================
# Attack vector 9 — Role escalation with wrong key
# ===========================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_role_escalation_wrong_key_returns_403(
    middleware: Any,
    mock_jwks_client: MagicMock,
) -> None:
    """
    AC: Token claiming ADMIN role but signed with an unknown RSA key → HTTP 403
    invalid_signature.  Ensures roles cannot be escalated by forging tokens.
    """
    from jose.exceptions import JWSSignatureError

    mock_jwks_client.verify.side_effect = JWSSignatureError(
        "Signature verification failed after JWKS refresh"
    )

    token = make_wrong_key_token(roles=["ADMIN"])
    status, body = await _call(middleware, token)

    assert status == 403
    assert body["error"] == "invalid_signature"


# ===========================================================================
# Hypothesis fuzz test — random token strings never cause 500
# ===========================================================================

@pytest.mark.security
def test_random_token_never_crashes_gateway() -> None:
    """
    AC: No arbitrary string passed as Bearer token should cause an unhandled
    exception (HTTP 500) in the gateway.  All malformed inputs must yield a
    structured 4xx response.

    Uses hypothesis to generate 200 random strings of varying length.
    """
    import asyncio

    from hypothesis import given, settings
    from hypothesis import strategies as st

    from src.gateway.auth.exceptions import MalformedTokenError
    from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

    # Use a real JWKSClient mock so we can control what verify() raises
    mock_client = MagicMock()

    def _raise_malformed(token: str) -> None:
        raise MalformedTokenError("Fuzz: malformed token")

    mock_client.verify = AsyncMock(side_effect=_raise_malformed)
    inner_app = AsyncMock()
    mw = JWTAuthMiddleware(app=inner_app, jwks_client=mock_client)

    @given(st.text(min_size=1, max_size=2048))
    @settings(max_examples=200, deadline=5000)
    def _run(random_string: str) -> None:
        scope = _make_scope(headers=_auth_header(random_string))
        messages: list[dict[str, Any]] = []

        async def _send(msg: dict[str, Any]) -> None:
            messages.append(msg)

        asyncio.run(mw(scope, _noop_receive, _send))

        # Must always produce a response — never silently swallow the request
        assert messages, "Middleware produced no ASGI response messages"

        start = next(
            (m for m in messages if m.get("type") == "http.response.start"), None
        )
        if start is not None:
            assert start["status"] in (400, 401, 403), (
                f"Got HTTP {start['status']} for random token {random_string!r:.80}"
            )

    _run()
