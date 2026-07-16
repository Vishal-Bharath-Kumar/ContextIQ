"""
ASGI middleware that populates the per-request ``RequestContext``.

TASK-US003-04: Session Isolation for Concurrent Tool Calls.

This middleware must run **after** the JWT authentication middleware so that
``scope["state"]["user_id"]`` and ``scope["state"]["session_id"]`` are
already populated when ``RequestContextMiddleware`` executes.

Recommended middleware order (outermost → innermost):

1. ``ErrorHandlerMiddleware``   — catch-all exception barrier
2. ``CircuitBreakerMiddleware`` — short-circuit on open circuit
3. ``ConnectionTracingMiddleware`` — OTel connection spans
4. ``RequestContextMiddleware`` — populate RequestContext ← this file
5. FastMCP / FastAPI handlers

The ``_request_ctx.reset(token)`` call in the ``finally`` block is
mandatory — it prevents stale context from leaking between requests that
share an OS thread or are processed sequentially on the same event-loop slot.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from opentelemetry import trace

from src.gateway.context.request_context import (
    RequestContext,
    _request_ctx,
    set_request_context,
)

logger = logging.getLogger(__name__)

# Scope types that carry per-request user state.
_SCOPED_TYPES: frozenset[str] = frozenset({"http", "websocket"})


def _extract_user_id(scope: dict[str, Any]) -> str:
    """Read user_id from ASGI scope state; fall back to 'anonymous'."""
    state: dict[str, Any] = scope.get("state") or {}
    return str(state.get("user_id", "anonymous"))


def _extract_session_id(scope: dict[str, Any]) -> str:
    """Read session_id from ASGI scope state; generate a stable fallback."""
    state: dict[str, Any] = scope.get("state") or {}
    if "session_id" in state:
        return str(state["session_id"])
    # Derive a deterministic-ish session ID from connection-level identifiers
    # when no JWT middleware has set one (e.g. unauthenticated health probes).
    client = scope.get("client")
    path = scope.get("path", "")
    if client:
        return f"{client[0]}:{client[1]}:{path}"
    return str(uuid4())


def _extract_trace_id(scope: dict[str, Any]) -> int:  # noqa: ARG001
    """Return the current OTel trace ID integer, or 0 if no span is active."""
    try:
        span_ctx = trace.get_current_span().get_span_context()
        return span_ctx.trace_id if span_ctx.trace_id else 0
    except Exception:  # noqa: BLE001
        return 0


def _extract_username(scope: dict[str, Any]) -> str:
    """Read username from JWT claims in scope state; fall back to empty string."""
    state: dict[str, Any] = scope.get("state") or {}
    jwt_claims = state.get("jwt_claims")
    if jwt_claims is not None:
        return getattr(jwt_claims, "preferred_username", None) or ""
    return ""


def _extract_roles(scope: dict[str, Any]) -> frozenset[str]:
    """Read merged roles from JWT claims in scope state; fall back to empty set."""
    state: dict[str, Any] = scope.get("state") or {}
    jwt_claims = state.get("jwt_claims")
    if jwt_claims is not None:
        try:
            return frozenset(jwt_claims.roles)
        except Exception:  # noqa: BLE001
            pass
    return frozenset()


class RequestContextMiddleware:
    """ASGI middleware that stamps each request with a fresh ``RequestContext``.

    Populates:
    - ``request_id`` — new UUID v4 per HTTP/WebSocket request
    - ``user_id``    — from ``scope["state"]["user_id"]`` (JWT middleware)
    - ``session_id`` — from ``scope["state"]["session_id"]`` (JWT middleware)
    - ``trace_id``   — from the active OTel span context

    The context is reset via ``_request_ctx.reset(token)`` in a ``finally``
    block so no state bleeds across requests.

    Parameters
    ----------
    app:
        The next ASGI application in the middleware chain.
    """

    def __init__(self, app: Any) -> None:  # noqa: ANN401
        self._app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,  # noqa: ANN401
        send: Any,  # noqa: ANN401
    ) -> None:
        if scope.get("type") not in _SCOPED_TYPES:
            await self._app(scope, receive, send)
            return

        ctx = RequestContext(
            request_id=str(uuid4()),
            user_id=_extract_user_id(scope),
            username=_extract_username(scope),
            roles=_extract_roles(scope),
            session_id=_extract_session_id(scope),
            trace_id=_extract_trace_id(scope),
        )
        token = set_request_context(ctx)
        logger.debug(
            "RequestContext set: request_id=%s user_id=%s session_id=%s",
            ctx.request_id,
            ctx.user_id,
            ctx.session_id,
        )
        try:
            await self._app(scope, receive, send)
        finally:
            _request_ctx.reset(token)
