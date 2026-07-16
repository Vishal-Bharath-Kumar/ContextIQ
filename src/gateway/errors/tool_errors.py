"""
Structured error helpers for the MCP ``tools/call`` pipeline.

TASK-US003-03: Structured Error Handling for Tool Call Failures.

Provides:
- MCP error code constants aligned with the JSON-RPC / MCP spec.
- ``build_tool_error()`` — factory that produces a valid MCP ``CallToolResult``
  content block with ``isError=True`` semantics so the session is never dropped.
"""
from __future__ import annotations

import json

from mcp.types import TextContent

# ---------------------------------------------------------------------------
# MCP / JSON-RPC error code constants
# ---------------------------------------------------------------------------

#: Input validation failure (tool not found, schema violation).
INVALID_PARAMS: int = -32602

#: Generic server-side error (timeout, 5xx, pipeline failure, unexpected exc).
INTERNAL_ERROR: int = -32603

#: Circuit breaker is open — service temporarily unavailable.
CIRCUIT_BREAKER_OPEN: int = -32001


# ---------------------------------------------------------------------------
# Error payload factory
# ---------------------------------------------------------------------------


def build_tool_error(
    code: int,
    message: str,
    detail: dict | None = None,
) -> list[TextContent]:
    """Return a single-item ``TextContent`` list encoding a structured MCP error.

    The returned value is a valid ``CallToolResult`` content block.  Callers
    **return** this from the ``call_tool`` handler (rather than raising) so the
    MCP session stays open and the ``isError`` flag is set in the protocol layer.

    Parameters
    ----------
    code:
        JSON-RPC / MCP error code.  Use the constants defined in this module
        (``INVALID_PARAMS``, ``INTERNAL_ERROR``, ``CIRCUIT_BREAKER_OPEN``).
    message:
        Human-readable error message surfaced to the MCP client.
    detail:
        Optional dict of additional structured data (e.g. ``{"tool": name}``
        or ``{"retry_after_seconds": 60}``).  Serialised under ``error.data``.
    """
    payload: dict = {"error": {"code": code, "message": message}}
    if detail:
        payload["error"]["data"] = detail
    return [TextContent(type="text", text=json.dumps(payload))]
