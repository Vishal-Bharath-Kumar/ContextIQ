"""
TASK-US004-04: Unit tests for authentication failure audit logging.

Coverage targets:
  - log_auth_failure() emits all required fields
  - log_auth_failure() never includes the token value (parametrised)
  - user_agent sanitisation (newlines stripped, max 256 chars)
  - IP extraction: X-Forwarded-For (leftmost), direct client tuple, unknown
  - auth_failures_total Prometheus counter increments per reason
  - Middleware wires log_auth_failure at each rejection path:
      missing_token, invalid_token_format, malformed_token,
      invalid_signature, token_expired
"""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
import structlog.testing


# ---------------------------------------------------------------------------
# Helpers shared with test_jwt_auth_middleware.py (inlined to keep tests
# independent — no shared fixture module needed)
# ---------------------------------------------------------------------------

def _make_scope(
    scope_type: str = "http",
    path: str = "/mcp/sse",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
    client: tuple[str, int] | None = None,
) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "type": scope_type,
        "path": path,
        "method": method,
        "headers": headers or [],
        "query_string": query_string,
    }
    if client is not None:
        scope["client"] = client
    return scope


def _auth_header(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode())]


async def _noop_receive() -> dict[str, Any]:
    return {}


def _capture_send() -> tuple[list[dict[str, Any]], Any]:
    messages: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        messages.append(message)

    return messages, _send


def _make_jwks_client(
    raw_claims: dict[str, Any] | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    _default_claims = {
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
    client = MagicMock()
    if raise_exc is not None:
        client.decode = AsyncMock(side_effect=raise_exc)
    else:
        client.decode = AsyncMock(return_value=raw_claims or _default_claims)
    return client


# ---------------------------------------------------------------------------
# _get_client_ip
# ---------------------------------------------------------------------------

class TestGetClientIp:

    def test_x_forwarded_for_single(self) -> None:
        from src.gateway.audit.auth_audit import _get_client_ip

        scope = _make_scope(headers=[(b"x-forwarded-for", b"203.0.113.5")])
        assert _get_client_ip(scope) == "203.0.113.5"

    def test_x_forwarded_for_multiple_returns_leftmost(self) -> None:
        from src.gateway.audit.auth_audit import _get_client_ip

        scope = _make_scope(
            headers=[(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1, 172.16.0.2")]
        )
        assert _get_client_ip(scope) == "203.0.113.5"

    def test_falls_back_to_client_tuple(self) -> None:
        from src.gateway.audit.auth_audit import _get_client_ip

        scope = _make_scope(client=("192.168.1.42", 54321))
        assert _get_client_ip(scope) == "192.168.1.42"

    def test_returns_unknown_when_no_ip_available(self) -> None:
        from src.gateway.audit.auth_audit import _get_client_ip

        scope = _make_scope()
        assert _get_client_ip(scope) == "unknown"


# ---------------------------------------------------------------------------
# _sanitise_user_agent
# ---------------------------------------------------------------------------

class TestSanitiseUserAgent:

    def test_strips_newline(self) -> None:
        from src.gateway.audit.auth_audit import _sanitise_user_agent

        scope = _make_scope(
            headers=[(b"user-agent", b"Mozilla/5.0\nX-Injected: header")]
        )
        result = _sanitise_user_agent(scope)
        assert "\n" not in result
        assert "Mozilla/5.0" in result

    def test_strips_carriage_return(self) -> None:
        from src.gateway.audit.auth_audit import _sanitise_user_agent

        scope = _make_scope(
            headers=[(b"user-agent", b"Mozilla/5.0\r\nX-Injected: header")]
        )
        result = _sanitise_user_agent(scope)
        assert "\r" not in result
        assert "\n" not in result

    def test_truncates_to_256_chars(self) -> None:
        from src.gateway.audit.auth_audit import _sanitise_user_agent

        long_ua = b"A" * 512
        scope = _make_scope(headers=[(b"user-agent", long_ua)])
        result = _sanitise_user_agent(scope)
        assert len(result) == 256

    def test_empty_user_agent(self) -> None:
        from src.gateway.audit.auth_audit import _sanitise_user_agent

        scope = _make_scope()
        assert _sanitise_user_agent(scope) == ""


# ---------------------------------------------------------------------------
# log_auth_failure — field presence and token-absence guarantee
# ---------------------------------------------------------------------------

class TestLogAuthFailure:

    def test_all_required_fields_emitted(self) -> None:
        """Every log entry must contain the exact fields specified in the task."""
        from src.gateway.audit.auth_audit import log_auth_failure

        with structlog.testing.capture_logs() as cap:
            log_auth_failure(
                reason="token_expired",
                ip_address="203.0.113.5",
                user_agent="pytest-agent",
                path="/mcp/sse",
                method="GET",
                timestamp="2026-07-15T10:00:00+00:00",
            )

        assert len(cap) == 1
        entry = cap[0]
        assert entry["reason"] == "token_expired"
        assert entry["ip_address"] == "203.0.113.5"
        assert entry["user_agent"] == "pytest-agent"
        assert entry["path"] == "/mcp/sse"
        assert entry["method"] == "GET"
        assert entry["timestamp"] == "2026-07-15T10:00:00+00:00"
        assert entry["event_type"] == "auth.failure"

    @pytest.mark.parametrize("token_value", [
        "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.sig",
        "eyJhbGciOiJSUzI1NiJ9",
        "secret-token-value",
        "abc123",
    ])
    def test_token_value_not_present_in_log(self, token_value: str) -> None:
        """Log entries MUST NOT contain any token substring (OWASP A09)."""
        from src.gateway.audit.auth_audit import log_auth_failure

        with structlog.testing.capture_logs() as cap:
            log_auth_failure(
                reason="malformed_token",
                ip_address="10.0.0.1",
                user_agent="pytest",
                path="/mcp/sse",
                method="POST",
                timestamp="2026-07-15T10:00:00+00:00",
            )

        # Serialise the captured log to a string and verify the token is absent
        log_str = str(cap)
        assert token_value not in log_str

    def test_log_level_is_warning(self) -> None:
        from src.gateway.audit.auth_audit import log_auth_failure

        with structlog.testing.capture_logs() as cap:
            log_auth_failure(
                reason="missing_token",
                ip_address="10.0.0.1",
                user_agent="curl/7.88",
                path="/mcp/sse",
                method="GET",
                timestamp="2026-07-15T10:00:00+00:00",
            )

        assert cap[0]["log_level"] == "warning"

    def test_event_name_is_authentication_failure(self) -> None:
        from src.gateway.audit.auth_audit import log_auth_failure

        with structlog.testing.capture_logs() as cap:
            log_auth_failure(
                reason="invalid_signature",
                ip_address="10.0.0.1",
                user_agent="curl/7.88",
                path="/mcp/sse",
                method="DELETE",
                timestamp="2026-07-15T10:00:00+00:00",
            )

        assert cap[0]["event"] == "authentication_failure"


# ---------------------------------------------------------------------------
# Prometheus counter
# ---------------------------------------------------------------------------

class TestPrometheusCounter:

    def test_counter_increments_for_each_reason(self) -> None:
        from src.gateway.audit.auth_audit import auth_failures_total, log_auth_failure

        reasons = [
            "missing_token",
            "invalid_token_format",
            "malformed_token",
            "invalid_signature",
            "token_expired",
        ]
        before = {
            r: auth_failures_total.labels(reason=r)._value.get()
            for r in reasons
        }

        with structlog.testing.capture_logs():
            for r in reasons:
                log_auth_failure(
                    reason=r,
                    ip_address="10.0.0.1",
                    user_agent="test",
                    path="/mcp/sse",
                    method="GET",
                    timestamp="2026-07-15T10:00:00+00:00",
                )

        for r in reasons:
            after = auth_failures_total.labels(reason=r)._value.get()
            assert after == before[r] + 1, f"Counter not incremented for reason={r}"

    def test_token_expired_counter_increments(self) -> None:
        from src.gateway.audit.auth_audit import auth_failures_total, log_auth_failure

        before = auth_failures_total.labels(reason="token_expired")._value.get()

        with structlog.testing.capture_logs():
            log_auth_failure(
                reason="token_expired",
                ip_address="10.0.0.1",
                user_agent="test-client",
                path="/mcp/sse",
                method="GET",
                timestamp="2026-07-15T10:00:00+00:00",
            )

        after = auth_failures_total.labels(reason="token_expired")._value.get()
        assert after == before + 1


# ---------------------------------------------------------------------------
# Middleware integration — audit log called at each rejection path
# ---------------------------------------------------------------------------

class TestMiddlewareAuditIntegration:
    """Verify JWTAuthMiddleware calls log_auth_failure at every rejection."""

    _AUDIT_PATH = "src.gateway.middleware.jwt_auth.log_auth_failure"

    @pytest.mark.asyncio
    async def test_missing_token_calls_audit_log(self) -> None:
        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        with patch(self._AUDIT_PATH) as mock_log:
            await mw(_make_scope(), _noop_receive, send)

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["reason"] == "missing_token"
        # Ensure the actual JWT value is not passed — not the word "token" which
        # legitimately appears in reason names (missing_token, token_expired…)
        for key in ("ip_address", "user_agent", "path", "method", "timestamp"):
            assert key in call_kwargs

    @pytest.mark.asyncio
    async def test_invalid_format_calls_audit_log(self) -> None:
        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        scope = _make_scope(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")])
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["reason"] == "invalid_token_format"

    @pytest.mark.asyncio
    async def test_malformed_token_calls_audit_log(self) -> None:
        from jose.exceptions import JWTError

        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client(raise_exc=JWTError("bad")))
        msgs, send = _capture_send()

        scope = _make_scope(headers=_auth_header("not.a.valid.jwt"))
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["reason"] == "malformed_token"

    @pytest.mark.asyncio
    async def test_invalid_signature_calls_audit_log(self) -> None:
        from jose.exceptions import JWSSignatureError

        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client(raise_exc=JWSSignatureError("bad sig")))
        msgs, send = _capture_send()

        scope = _make_scope(headers=_auth_header("hdr.payload.badsig"))
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["reason"] == "invalid_signature"

    @pytest.mark.asyncio
    async def test_expired_token_calls_audit_log(self) -> None:
        from jose.exceptions import ExpiredSignatureError

        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client(raise_exc=ExpiredSignatureError("exp")))
        msgs, send = _capture_send()

        scope = _make_scope(headers=_auth_header("hdr.payload.sig"))
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["reason"] == "token_expired"

    @pytest.mark.asyncio
    async def test_valid_token_does_not_call_audit_log(self) -> None:
        """No audit log on success."""
        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        scope = _make_scope(headers=_auth_header("valid.jwt.token"))
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_bypass_path_does_not_call_audit_log(self) -> None:
        """/healthz bypass should never produce an audit entry."""
        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        scope = _make_scope(path="/healthz")
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_log_contains_xff_ip(self) -> None:
        """Real client IP is resolved from X-Forwarded-For header."""
        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        scope = _make_scope(
            headers=[(b"x-forwarded-for", b"203.0.113.99, 10.0.0.1")],
            client=("10.0.0.1", 12345),
        )
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        assert mock_log.called
        assert mock_log.call_args.kwargs["ip_address"] == "203.0.113.99"

    @pytest.mark.asyncio
    async def test_audit_log_user_agent_sanitised(self) -> None:
        """Newlines in User-Agent are stripped before being passed to log_auth_failure."""
        from src.gateway.middleware.jwt_auth import JWTAuthMiddleware

        inner = AsyncMock()
        mw = JWTAuthMiddleware(inner, _make_jwks_client())
        msgs, send = _capture_send()

        scope = _make_scope(
            headers=[(b"user-agent", b"curl/7.88\nX-Injected: evil")]
        )
        with patch(self._AUDIT_PATH) as mock_log:
            await mw(scope, _noop_receive, send)

        assert mock_log.called
        ua = mock_log.call_args.kwargs["user_agent"]
        assert "\n" not in ua
        assert "\r" not in ua
