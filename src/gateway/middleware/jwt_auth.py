"""
ASGI JWT Authentication Middleware for the ContextIQ MCP Gateway.

TASK-US004-01: Implement an ASGI middleware that intercepts every inbound HTTP
and WebSocket request, extracts the ``Authorization: Bearer <token>`` header,
and enforces Keycloak JWT authentication before any handler executes.

Decision tree
-------------
Inbound request
│
├─ Non-HTTP/WS scope (lifespan) → pass through unchanged
├─ Path in _BYPASS_PATHS (/healthz, /metrics, …) → pass through unchanged
│
├─ No Authorization header AND no ?token= param → HTTP 401
│    {"error": "missing_token", "message": "Authorization header required"}
│
├─ Header present but not "Bearer <token>" format → HTTP 401
│    {"error": "invalid_token_format"}
│
├─ Token decode fails (malformed JWT) → HTTP 401
│    {"error": "malformed_token"}
│
├─ Signature verification fails → HTTP 403
│    {"error": "invalid_signature"}
│
├─ Token expired (exp claim) → HTTP 401
│    WWW-Authenticate: Bearer error="invalid_token",
│                              error_description="Token expired"
│    {"error": "token_expired"}
│
└─ Valid token → populate scope["state"] with claims, user_id, session_id
                 → call next middleware

WebSocket note
--------------
Browser WebSocket APIs cannot set custom headers, so the token may arrive as a
``?token=<jwt>`` query-string parameter.  The ``Authorization`` header is checked
first; the query param is used only as a fallback and is logged at DEBUG level.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from src.gateway.audit.auth_audit import (
    _get_client_ip,
    _sanitise_user_agent,
    log_auth_failure,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Paths that bypass JWT validation entirely.
# OWASP A01: access control — allow unauthenticated only for safe probe paths.
# ---------------------------------------------------------------------------
_BYPASS_PATHS: frozenset[str] = frozenset({
    "/healthz",
    "/metrics",
    "/auth/health/ready",
    "/auth/health/live",
    "/docs",
    "/redoc",
    "/openapi.json",
})

# ---------------------------------------------------------------------------
# Known platform role values (case-insensitive) — TASK-US004-03
# Unknown roles are silently ignored (not rejected) but trigger a WARNING.
# ---------------------------------------------------------------------------
_KNOWN_ROLES: frozenset[str] = frozenset({
    "developer",
    "platform_engineer",
    "devops_sre",
    "admin",
    "security_officer",
    "manager",
    "auditor",
})


def _warn_unknown_roles(roles: frozenset[str], path: str | None) -> None:
    """Emit a WARNING for any role not in _KNOWN_ROLES (case-insensitive)."""
    unknown = frozenset(r for r in roles if r.lower() not in _KNOWN_ROLES)
    if unknown:
        logger.warning(
            "JWT contains unknown roles for path=%s roles=%s",
            path,
            sorted(unknown),
        )

# ---------------------------------------------------------------------------
# Minimal ASGI response helpers (no external dependencies)
# ---------------------------------------------------------------------------

def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode()


def _error_body(error: str, message: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": error}
    if message is not None:
        body["message"] = message
    return body


async def _send_http_error(
    send: Any,
    status: int,
    error: str,
    message: str | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = _json_bytes(_error_body(error, message))
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _close_websocket(send: Any, code: int = 4001) -> None:
    """Reject a WebSocket handshake with a close frame."""
    await send({"type": "websocket.close", "code": code})


# ---------------------------------------------------------------------------
# Token extraction helpers
# ---------------------------------------------------------------------------

def _bearer_token_from_headers(scope: dict[str, Any]) -> str | None:
    """Extract the raw token string from ``Authorization: Bearer <token>``."""
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            auth = value.decode("latin-1").strip()
            if not auth.startswith("Bearer "):
                return ""   # sentinel: header present but wrong scheme
            return auth[len("Bearer "):].strip()
    return None   # header absent


def _token_from_query_string(scope: dict[str, Any]) -> str | None:
    """Extract ``token=...`` from the URL query string (WebSocket fallback)."""
    qs = scope.get("query_string", b"")
    if not qs:
        return None
    params = urllib.parse.parse_qs(qs.decode("latin-1"))
    tokens = params.get("token", [])
    return tokens[0] if tokens else None


# ---------------------------------------------------------------------------
# JWTAuthMiddleware
# ---------------------------------------------------------------------------

class JWTAuthMiddleware:
    """Pure ASGI JWT authentication middleware.

    Registered **outermost** in the middleware stack (before all other
    middleware) so that unauthenticated requests are rejected before reaching
    circuit-breaker, tracing, or tool-handler code.

    Parameters
    ----------
    app:
        The next ASGI application in the middleware chain.
    jwks_client:
        A :class:`~src.auth.jwks_client.JWKSClient` instance pre-started via
        ``await jwks_client.startup()``.  Injected at construction time so it
        can be mocked in tests without patching globals.
    """

    def __init__(self, app: Any, jwks_client: Any) -> None:  # noqa: ANN401
        self._app = app
        self._jwks = jwks_client

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,  # noqa: ANN401
        send: Any,  # noqa: ANN401
    ) -> None:
        scope_type: str = scope.get("type", "")

        # Pass lifespan and unknown scope types straight through.
        if scope_type not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        # Bypass auth for health/readiness probes and Prometheus scrapes.
        if scope.get("path") in _BYPASS_PATHS:
            await self._app(scope, receive, send)
            return

        # ------------------------------------------------------------------
        # Token extraction
        # ------------------------------------------------------------------
        raw_token_result = _bearer_token_from_headers(scope)

        if raw_token_result is None:
            # Authorization header is completely absent.
            # For WebSocket, try query-string fallback.
            if scope_type == "websocket":
                qs_token = _token_from_query_string(scope)
                if qs_token:
                    logger.debug(
                        "WebSocket auth via query-string token (lower-security path)"
                    )
                    raw_token_result = qs_token
                else:
                    await _close_websocket(send, code=4001)
                    return
            else:
                log_auth_failure(
                    reason="missing_token",
                    ip_address=_get_client_ip(scope),
                    user_agent=_sanitise_user_agent(scope),
                    path=scope.get("path", ""),
                    method=scope.get("method", ""),
                    timestamp=_utc_now_iso(),
                )
                await _send_http_error(
                    send, 401, "missing_token", "Authorization header required"
                )
                return

        if raw_token_result == "":
            # Header was present but not Bearer scheme.
            log_auth_failure(
                reason="invalid_token_format",
                ip_address=_get_client_ip(scope),
                user_agent=_sanitise_user_agent(scope),
                path=scope.get("path", ""),
                method=scope.get("method", ""),
                timestamp=_utc_now_iso(),
            )
            if scope_type == "websocket":
                await _close_websocket(send, code=4001)
            else:
                await _send_http_error(send, 401, "invalid_token_format")
            return

        token: str = raw_token_result

        # ------------------------------------------------------------------
        # Oversized-token guard (OWASP A04 — resource exhaustion / DoS mitigation).
        # 8 KB is well above any legitimate JWT; 64 KB is rejected to prevent
        # expensive RSA decode on junk data reaching jose.  HTTP 413 is also
        # enforced at the NGINX layer for external traffic.
        # ------------------------------------------------------------------
        _MAX_TOKEN_BYTES: int = 8 * 1024  # 8 KB hard limit
        if len(token.encode("latin-1", errors="replace")) >= _MAX_TOKEN_BYTES:
            logger.warning(
                "Oversized Bearer token rejected (len=%d) for path=%s",
                len(token),
                scope.get("path"),
            )
            if scope_type == "websocket":
                await _close_websocket(send, code=4001)
            else:
                await _send_http_error(send, 413, "token_too_large", "Bearer token exceeds maximum allowed size")
            return

        # ------------------------------------------------------------------
        # JWT verification
        # Supports both the enhanced gateway JWKSClient (verify() → JWTClaims)
        # and the legacy src.auth JWKSClient (decode() → dict).
        # Custom exceptions (ExpiredTokenError, InvalidSignatureError,
        # MalformedTokenError) inherit from their jose counterparts so the
        # single except-chain below catches both.
        # ------------------------------------------------------------------
        try:
            from jose.exceptions import ExpiredSignatureError, JWSSignatureError
        except ImportError:  # pragma: no cover
            ExpiredSignatureError = Exception  # type: ignore[assignment, misc]
            JWSSignatureError = Exception  # type: ignore[assignment, misc]

        try:
            from jose.exceptions import JWTError
        except ImportError:  # pragma: no cover
            JWTError = Exception  # type: ignore[assignment, misc]

        from src.gateway.auth.exceptions import ServiceUnavailableError  # noqa: PLC0415

        # Prefer verify() (new gateway JWKSClient); fall back to decode()
        # (legacy src.auth JWKSClient or mock).  Use inspect to ensure we only
        # call verify() when it is a real coroutine — prevents accidentally
        # calling a MagicMock attribute that looks like verify but isn't async.
        import inspect  # noqa: PLC0415
        _verify_attr = getattr(self._jwks, "verify", None)
        _verify = (
            _verify_attr
            if (_verify_attr is not None and inspect.iscoroutinefunction(_verify_attr))
            else self._jwks.decode
        )

        try:
            result = await _verify(token)
        except ServiceUnavailableError:
            logger.warning("JWKS unavailable for path=%s", scope.get("path"))
            if scope_type == "websocket":
                await _close_websocket(send, code=4001)
            else:
                body = _json_bytes(
                    _error_body("service_unavailable", "Auth service temporarily unavailable")
                )
                await send({
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"retry-after", b"30"),
                    ],
                })
                await send({"type": "http.response.body", "body": body, "more_body": False})
            return
        except ExpiredSignatureError:
            logger.debug("JWT expired for path=%s", scope.get("path"))
            log_auth_failure(
                reason="token_expired",
                ip_address=_get_client_ip(scope),
                user_agent=_sanitise_user_agent(scope),
                path=scope.get("path", ""),
                method=scope.get("method", ""),
                timestamp=_utc_now_iso(),
            )
            if scope_type == "websocket":
                await _close_websocket(send, code=4001)
            else:
                await _send_http_error(
                    send,
                    401,
                    "token_expired",
                    extra_headers=[
                        (
                            b"www-authenticate",
                            b'Bearer error="invalid_token", error_description="Token expired"',
                        )
                    ],
                )
            return
        except JWSSignatureError:
            logger.debug("JWT signature invalid for path=%s", scope.get("path"))
            log_auth_failure(
                reason="invalid_signature",
                ip_address=_get_client_ip(scope),
                user_agent=_sanitise_user_agent(scope),
                path=scope.get("path", ""),
                method=scope.get("method", ""),
                timestamp=_utc_now_iso(),
            )
            if scope_type == "websocket":
                await _close_websocket(send, code=4003)
            else:
                await _send_http_error(send, 403, "invalid_signature")
            return
        except JWTError as exc:
            logger.debug("JWT malformed for path=%s: %s", scope.get("path"), exc)
            log_auth_failure(
                reason="malformed_token",
                ip_address=_get_client_ip(scope),
                user_agent=_sanitise_user_agent(scope),
                path=scope.get("path", ""),
                method=scope.get("method", ""),
                timestamp=_utc_now_iso(),
            )
            if scope_type == "websocket":
                await _close_websocket(send, code=4001)
            else:
                await _send_http_error(send, 401, "malformed_token")
            return

        # ------------------------------------------------------------------
        # Populate ASGI scope state for downstream middleware / handlers
        # ------------------------------------------------------------------
        # Import JWTClaims lazily to avoid a circular import:
        # auth_types → src.auth.roles → src.auth.__init__ → dependencies → auth_types
        from src.gateway.schemas.auth_types import JWTClaims  # noqa: PLC0415

        # result may be a JWTClaims (from verify()) or a raw dict (from decode()).
        if isinstance(result, dict):
            claims = JWTClaims(**result)
        else:
            claims = result  # already a JWTClaims from verify()

        scope.setdefault("state", {})
        scope["state"]["jwt_claims"] = claims
        # Convenience keys consumed by RequestContextMiddleware (TASK-US003-04)
        scope["state"]["user_id"] = claims.sub
        scope["state"]["session_id"] = claims.jti or claims.sub

        # ------------------------------------------------------------------
        # Build and bind RequestContext — TASK-US004-03
        # ------------------------------------------------------------------
        from uuid import uuid4  # noqa: PLC0415

        from opentelemetry import trace  # noqa: PLC0415

        from src.gateway.context.request_context import (  # noqa: PLC0415
            RequestContext,
            set_request_context,
        )

        span_ctx = trace.get_current_span().get_span_context()
        ctx = RequestContext(
            request_id=str(uuid4()),
            user_id=claims.sub,
            username=claims.preferred_username or "",
            roles=frozenset(claims.roles),
            session_id=claims.jti or claims.sub,
            trace_id=span_ctx.trace_id,
        )
        _warn_unknown_roles(ctx.roles, scope.get("path"))
        token = set_request_context(ctx)
        try:
            await self._app(scope, receive, send)
        finally:
            from src.gateway.context.request_context import _request_ctx  # noqa: PLC0415
            _request_ctx.reset(token)
