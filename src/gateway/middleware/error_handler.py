"""
ASGI catch-all exception middleware for the ContextIQ MCP Gateway.

TASK-US003-03: Structured Error Handling for Tool Call Failures.

Catches any unhandled exception that escapes the FastMCP / FastAPI handler
stack and returns a JSON-RPC ``-32603`` error response instead of letting
the ASGI server reset the connection (which would terminate the MCP session).

Only HTTP connections are handled here; WebSocket and lifespan scopes are
forwarded unchanged.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_FALLBACK_BODY: bytes = json.dumps(
    {
        "jsonrpc": "2.0",
        "error": {
            "code": -32603,
            "message": "Internal server error",
        },
        "id": None,
    }
).encode()


class ErrorHandlerMiddleware:
    """ASGI middleware that converts unhandled exceptions to structured 500 responses.

    Sits outermost in the middleware stack so it catches exceptions from any
    inner middleware or handler.  WebSocket and lifespan scopes are passed
    through unmodified.

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
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        try:
            await self._app(scope, receive, send)
        except Exception:
            logger.exception(
                "Unhandled exception in gateway — returning structured 500",
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_FALLBACK_BODY)).encode()),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": _FALLBACK_BODY,
                    "more_body": False,
                }
            )
