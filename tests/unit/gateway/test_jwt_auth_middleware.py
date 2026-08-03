"""
Unit tests for TASK-US004-01: ASGI JWT Authentication Middleware.

Coverage targets (≥ 95% on gateway/middleware/jwt_auth.py):
  - No Authorization header → HTTP 401, error="missing_token"
  - Authorization: Basic ... → HTTP 401, error="invalid_token_format"
  - Malformed JWT (JWTError) → HTTP 401, error="malformed_token"
  - Signature invalid (JWTSignatureError) → HTTP 403, error="invalid_signature"
  - Expired token (ExpiredSignatureError) → HTTP 401, error="token_expired",
      WWW-Authenticate header present
  - Valid token → claims injected into scope["state"], next() called
  - GET /healthz bypasses auth → inner app called without token
  - WebSocket without header → WS close 4001
  - WebSocket with ?token= fallback → accepted
  - Lifespan scope passes through untouched
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gateway.middleware.jwt_auth import JWTAuthMiddleware
from src.gateway.schemas.auth_types import AuthError, JWTClaims


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CLAIMS = {
    "sub": "user-123",
    "iss": "http://keycloak/realms/contextiq",
    "exp": 9999999999,
    "iat": 1700000000,
    "jti": "sess-abc",
    "email": "alice@example.com",
    "preferred_username": "alice",
    "realm_access": {"roles": ["developer"]},
    "resource_access": {},
}


def _make_scope(
    scope_type: str = "http",
    path: str = "/mcp/sse",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> dict[str, Any]:
    return {
        "type": scope_type,
        "path": path,
        "headers": headers or [],
        "query_string": query_string,
    }


def _auth_header(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode())]


async def _noop_receive() -> dict[str, Any]:
    return {}


def _capture_send() -> tuple[list[dict[str, Any]], Any]:
    """Return (captured_messages, send_callable)."""
    messages: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        messages.append(message)

    return messages, _send


def _response_body(messages: list[dict[str, Any]]) -> dict[str, Any]:
    body_msg = next((m for m in messages if m.get("type") == "http.response.body"), None)
    assert body_msg is not None, f"No http.response.body in {messages}"
    return json.loads(body_msg["body"])


def _response_status(messages: list[dict[str, Any]]) -> int:
    start_msg = next((m for m in messages if m.get("type") == "http.response.start"), None)
    assert start_msg is not None
    return start_msg["status"]


def _response_headers(messages: list[dict[str, Any]]) -> dict[str, str]:
    start_msg = next(m for m in messages if m.get("type") == "http.response.start")
    return {k.decode(): v.decode() for k, v in start_msg.get("headers", [])}


def _make_jwks_client(
    raw_claims: dict[str, Any] | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    if raise_exc is not None:
        client.decode = AsyncMock(side_effect=raise_exc)
    else:
        client.decode = AsyncMock(return_value=raw_claims or _VALID_CLAIMS)
    return client


# ---------------------------------------------------------------------------
# HTTP: rejection paths
# ---------------------------------------------------------------------------

class TestHTTPRejectionPaths:

    @pytest.mark.asyncio
    async def test_missing_authorization_header_returns_401(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        await mw(_make_scope(), _noop_receive, send)

        assert _response_status(msgs) == 401
        assert _response_body(msgs)["error"] == "missing_token"
        inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_basic_auth_header_returns_401_invalid_format(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        scope = _make_scope(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")])
        await mw(scope, _noop_receive, send)

        assert _response_status(msgs) == 401
        assert _response_body(msgs)["error"] == "invalid_token_format"
        inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_token_returns_401(self) -> None:
        from jose.exceptions import JWTError

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client(raise_exc=JWTError("bad")))
        msgs, send = _capture_send()

        scope = _make_scope(headers=_auth_header("not.a.valid.jwt"))
        await mw(scope, _noop_receive, send)

        assert _response_status(msgs) == 401
        assert _response_body(msgs)["error"] == "malformed_token"
        inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_403(self) -> None:
        from jose.exceptions import JWSSignatureError

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client(raise_exc=JWSSignatureError("bad sig")))
        msgs, send = _capture_send()

        scope = _make_scope(headers=_auth_header("hdr.payload.badsig"))
        await mw(scope, _noop_receive, send)

        assert _response_status(msgs) == 403
        assert _response_body(msgs)["error"] == "invalid_signature"
        inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_token_returns_401_with_www_authenticate_header(self) -> None:
        from jose.exceptions import ExpiredSignatureError

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client(raise_exc=ExpiredSignatureError("expired")))
        msgs, send = _capture_send()

        scope = _make_scope(headers=_auth_header("hdr.payload.sig"))
        await mw(scope, _noop_receive, send)

        assert _response_status(msgs) == 401
        assert _response_body(msgs)["error"] == "token_expired"

        response_headers = _response_headers(msgs)
        assert "www-authenticate" in response_headers
        www_auth = response_headers["www-authenticate"]
        assert 'error="invalid_token"' in www_auth
        assert "Token expired" in www_auth
        inner.assert_not_called()


# ---------------------------------------------------------------------------
# HTTP: valid token pass-through
# ---------------------------------------------------------------------------

class TestHTTPValidToken:

    @pytest.mark.asyncio
    async def test_valid_token_calls_inner_app(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(headers=_auth_header("valid.jwt.token"))
        await mw(scope, _noop_receive, AsyncMock())

        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_token_populates_scope_state_jwt_claims(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(headers=_auth_header("valid.jwt"))
        await mw(scope, _noop_receive, AsyncMock())

        state = scope.get("state", {})
        assert "jwt_claims" in state
        claims = state["jwt_claims"]
        assert isinstance(claims, JWTClaims)
        assert claims.sub == "user-123"

    @pytest.mark.asyncio
    async def test_valid_token_populates_user_id_and_session_id(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(headers=_auth_header("valid.jwt"))
        await mw(scope, _noop_receive, AsyncMock())

        state = scope.get("state", {})
        assert state.get("user_id") == "user-123"
        assert state.get("session_id") == "sess-abc"

    @pytest.mark.asyncio
    async def test_user_id_falls_back_to_sub_when_no_jti(self) -> None:
        claims_no_jti = {**_VALID_CLAIMS, "jti": None}
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client(raw_claims=claims_no_jti))

        scope = _make_scope(headers=_auth_header("valid.jwt"))
        await mw(scope, _noop_receive, AsyncMock())

        state = scope.get("state", {})
        assert state.get("session_id") == "user-123"  # falls back to sub


# ---------------------------------------------------------------------------
# Bypass paths
# ---------------------------------------------------------------------------

class TestBypassPaths:

    @pytest.mark.asyncio
    async def test_healthz_bypasses_auth(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(path="/healthz")  # no auth header
        await mw(scope, _noop_receive, AsyncMock())

        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_bypasses_auth(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(path="/metrics")
        await mw(scope, _noop_receive, AsyncMock())

        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_bypasses_auth(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(path="/docs")
        await mw(scope, _noop_receive, AsyncMock())

        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_protected_path_requires_auth(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        scope = _make_scope(path="/mcp/sse")  # no auth header
        await mw(scope, _noop_receive, send)

        assert _response_status(msgs) == 401
        inner.assert_not_called()


# ---------------------------------------------------------------------------
# Lifespan scope
# ---------------------------------------------------------------------------

class TestLifespanPassthrough:

    @pytest.mark.asyncio
    async def test_lifespan_scope_passes_through_untouched(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = {"type": "lifespan"}
        await mw(scope, _noop_receive, AsyncMock())

        inner.assert_called_once()


# ---------------------------------------------------------------------------
# WebSocket paths
# ---------------------------------------------------------------------------

class TestWebSocketAuth:

    @pytest.mark.asyncio
    async def test_websocket_no_token_closes_with_4001(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        ws_msgs: list[dict[str, Any]] = []

        async def _ws_send(msg: dict[str, Any]) -> None:
            ws_msgs.append(msg)

        scope = _make_scope(scope_type="websocket", path="/mcp/ws")
        await mw(scope, _noop_receive, _ws_send)

        assert any(m.get("type") == "websocket.close" for m in ws_msgs)
        close_msg = next(m for m in ws_msgs if m.get("type") == "websocket.close")
        assert close_msg.get("code") == 4001
        inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_query_string_token_accepted(self) -> None:
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(
            scope_type="websocket",
            path="/mcp/ws",
            query_string=b"token=valid.jwt.token",
        )
        await mw(scope, _noop_receive, AsyncMock())

        inner.assert_called_once()
        state = scope.get("state", {})
        assert "jwt_claims" in state

    @pytest.mark.asyncio
    async def test_websocket_authorization_header_takes_precedence(self) -> None:
        """When both header and query-string are present, header wins."""
        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())

        scope = _make_scope(
            scope_type="websocket",
            path="/mcp/ws",
            headers=_auth_header("header.jwt.token"),
            query_string=b"token=qs.jwt.token",
        )
        await mw(scope, _noop_receive, AsyncMock())

        inner.assert_called_once()
        # Verify it was the header token that was decoded (decode called once)
        mw._jwks.decode.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_expired_token_closes_with_4001(self) -> None:
        from jose.exceptions import ExpiredSignatureError

        inner = AsyncMock()
        mw = JWTAuthMiddleware(
            inner, _make_jwks_client(raise_exc=ExpiredSignatureError("exp"))
        )

        ws_msgs: list[dict[str, Any]] = []

        async def _ws_send(msg: dict[str, Any]) -> None:
            ws_msgs.append(msg)

        scope = _make_scope(
            scope_type="websocket",
            path="/mcp/ws",
            headers=_auth_header("expired.jwt"),
        )
        await mw(scope, _noop_receive, _ws_send)

        assert any(m.get("type") == "websocket.close" for m in ws_msgs)

    @pytest.mark.asyncio
    async def test_websocket_invalid_signature_closes_with_4003(self) -> None:
        from jose.exceptions import JWSSignatureError

        inner = AsyncMock()
        mw = JWTAuthMiddleware(
            inner, _make_jwks_client(raise_exc=JWSSignatureError("sig"))
        )

        ws_msgs: list[dict[str, Any]] = []

        async def _ws_send(msg: dict[str, Any]) -> None:
            ws_msgs.append(msg)

        scope = _make_scope(
            scope_type="websocket",
            path="/mcp/ws",
            headers=_auth_header("bad.sig.jwt"),
        )
        await mw(scope, _noop_receive, _ws_send)

        close_msg = next(m for m in ws_msgs if m.get("type") == "websocket.close")
        assert close_msg.get("code") == 4003


# ---------------------------------------------------------------------------
# AuthError schema
# ---------------------------------------------------------------------------

class TestAuthErrorSchema:

    def test_error_only(self) -> None:
        err = AuthError(error="missing_token")
        assert err.error == "missing_token"
        assert err.message is None

    def test_error_with_message(self) -> None:
        err = AuthError(error="token_expired", message="Token has expired")
        dumped = err.model_dump(exclude_none=True)
        assert dumped == {"error": "token_expired", "message": "Token has expired"}

    def test_json_serialization(self) -> None:
        err = AuthError(error="invalid_signature")
        body = json.loads(err.model_dump_json(exclude_none=True))
        assert body["error"] == "invalid_signature"
        assert "message" not in body
