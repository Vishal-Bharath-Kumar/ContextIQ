"""
Circuit-breaker ASGI middleware and protected downstream call.

TASK-US001-04: Add Circuit-Breaker Middleware to MCP Endpoint.

Two components are defined here:

1. ``CircuitBreakerMiddleware`` — ASGI middleware that short-circuits inbound
   HTTP POST requests when the circuit is open, returning a structured
   JSON-RPC error (code -32001) with 503 status immediately (< 10 ms).
   GET requests (SSE subscribe, health probes) are always forwarded.

2. ``call_agent_pipeline`` — async function that wraps the actual downstream
   call to the Agent Worker.  Protected via ``gateway_breaker.call_async`` so
   every failure is counted and state transitions are tracked automatically.

Callers that catch ``pybreaker.CircuitBreakerError`` must return the same
structured JSON-RPC error documented here.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pybreaker

from src.gateway.state import gateway_breaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured MCP error payload (JSON-RPC spec §5)
# ---------------------------------------------------------------------------

_CIRCUIT_OPEN_BODY: bytes = json.dumps(
    {
        "jsonrpc": "2.0",
        "error": {
            "code": -32001,
            "message": "Service temporarily unavailable. Circuit open.",
            "data": {"retry_after_seconds": 60},
        },
        "id": None,
    }
).encode()

# ---------------------------------------------------------------------------
# ASGI middleware
# ---------------------------------------------------------------------------


class CircuitBreakerMiddleware:
    """
    ASGI middleware that rejects HTTP POST requests when the circuit is open.

    Only POST requests are short-circuited (MCP message submissions).
    GET requests (SSE handshake, /healthz) bypass the check entirely.

    Parameters
    ----------
    app:
        The next ASGI application in the middleware chain.
    breaker:
        The ``CircuitBreaker`` instance to inspect.  Defaults to the module-
        level ``gateway_breaker`` singleton; override in tests for isolation.
    """

    def __init__(
        self,
        app: Any,
        breaker: pybreaker.CircuitBreaker = gateway_breaker,  # noqa: B008
    ) -> None:
        self._app = app
        self._breaker = breaker

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and self._breaker.current_state == pybreaker.STATE_OPEN
        ):
            logger.debug(
                "Circuit open — rejecting %s %s",
                scope.get("method"),
                scope.get("path"),
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_CIRCUIT_OPEN_BODY)).encode()),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": _CIRCUIT_OPEN_BODY,
                    "more_body": False,
                }
            )
            return

        await self._app(scope, receive, send)


# ---------------------------------------------------------------------------
# Protected downstream call
# ---------------------------------------------------------------------------


async def call_agent_pipeline(
    payload: dict[str, Any],
    breaker: pybreaker.CircuitBreaker = gateway_breaker,  # noqa: B008
) -> dict[str, Any]:
    """
    Call the downstream Agent Worker pipeline, protected by the circuit breaker.

    Tracks every success and failure; transitions the circuit state
    automatically through ``pybreaker``.

    Parameters
    ----------
    payload:
        The tool-call request body forwarded to the agent worker.
    breaker:
        Circuit-breaker instance to use.  Override in tests for isolation.

    Returns
    -------
    dict[str, Any]
        The JSON response from the agent worker.

    Raises
    ------
    pybreaker.CircuitBreakerError
        When the circuit is open; callers must return the structured error.
    """

    def _invoke() -> dict[str, Any]:  # pragma: no cover
        # NOTE: This stub will be replaced in TASK-US001-05 / US-036 with a
        # real async HTTP call to the agent-worker service.
        return {}

    # Use asyncio.to_thread so pybreaker's sync call() correctly tracks
    # failures and state transitions without requiring tornado (which
    # pybreaker.call_async depends on).
    return await asyncio.to_thread(breaker.call, _invoke)
