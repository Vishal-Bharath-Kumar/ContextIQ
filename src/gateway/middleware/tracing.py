"""
ASGI tracing middleware for MCP connection lifecycle spans.

TASK-US001-05: Instrument MCP Connections with OpenTelemetry Spans.

This middleware tracks every WebSocket and SSE transport connection as a pair
of sibling spans under the root HTTP trace:

* ``mcp.connection.open``  — emitted when a WebSocket / SSE connection is
  accepted.  Attributes: ``mcp.transport``, ``net.peer.ip``.

* ``mcp.connection.close`` — emitted when the same connection is torn down.
  Attributes: ``mcp.transport``, ``net.peer.ip``,
  ``mcp.session_duration_ms``.

The middleware also sets the ``mcp_transport`` ContextVar (via
``set_transport_context``) so downstream handlers can attach ``mcp.transport``
to their own spans without needing access to the ASGI scope.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from src.gateway.telemetry import get_tracer, set_transport_context

logger = logging.getLogger(__name__)

# ASGI scope types that represent MCP transport connections.
_TRANSPORT_SCOPE_TYPES: frozenset[str] = frozenset({"websocket", "http"})


def _detect_transport(scope: dict[str, Any]) -> str | None:
    """Return ``'websocket'`` or ``'sse'`` based on the ASGI scope, else ``None``."""
    scope_type: str = scope.get("type", "")
    if scope_type == "websocket":
        return "websocket"
    if scope_type == "http":
        path: str = scope.get("path", "")
        if path.endswith("/sse"):
            return "sse"
    return None


def _peer_ip(scope: dict[str, Any]) -> str:
    """Extract the client IP address from scope, honouring X-Forwarded-For."""
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for name, value in headers:
        if name.lower() == b"x-forwarded-for":
            return value.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"


class ConnectionTracingMiddleware:
    """
    ASGI middleware that emits ``mcp.connection.open`` / ``mcp.connection.close``
    spans for WebSocket and SSE connections.

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
        transport = _detect_transport(scope)
        if transport is None:
            await self._app(scope, receive, send)
            return

        peer_ip = _peer_ip(scope)
        start_ms = time.monotonic() * 1000.0

        # Store transport in context so handlers can attach it to their spans.
        set_transport_context(transport)

        tracer = get_tracer()

        try:
            from opentelemetry.trace import SpanKind

            with tracer.start_as_current_span(
                "mcp.connection.open",
                kind=SpanKind.SERVER,
            ) as open_span:
                open_span.set_attribute("mcp.transport", transport)
                open_span.set_attribute("net.peer.ip", peer_ip)
                logger.debug(
                    "MCP connection open: transport=%r peer=%r",
                    transport,
                    peer_ip,
                )

            try:
                await self._app(scope, receive, send)
            except Exception:
                logger.warning(
                    "ConnectionTracingMiddleware: inner app raised — "
                    "connection closed with error.",
                    exc_info=True,
                )
                return

            duration_ms = time.monotonic() * 1000.0 - start_ms
            with tracer.start_as_current_span(
                "mcp.connection.close",
                kind=SpanKind.SERVER,
            ) as close_span:
                close_span.set_attribute("mcp.transport", transport)
                close_span.set_attribute("net.peer.ip", peer_ip)
                close_span.set_attribute("mcp.session_duration_ms", round(duration_ms, 2))
                logger.debug(
                    "MCP connection close: transport=%r peer=%r duration_ms=%.2f",
                    transport,
                    peer_ip,
                    duration_ms,
                )

        except ImportError:
            # OTel SDK not installed — silently pass through.
            await self._app(scope, receive, send)
