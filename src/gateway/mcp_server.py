"""
FastMCP server instance and transport registration.

TASK-US001-01: Configure FastMCP Server with SSE and WebSocket Transport.

The SSE ASGI app is created here and imported by gateway/main.py for mounting.
The ``mcp`` instance is the single FastMCP server used across all transports so
that tools and resources registered on it are available via both SSE and WebSocket.
"""
from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan

from src.gateway.config import settings
from src.gateway.handlers.initialize import register_initialize_handler
from src.gateway.handlers.tools_call import register_tools_call_handler
from src.gateway.handlers.tools_list import register_tools_list_handler

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------
mcp: FastMCP = FastMCP(
    name="ContextIQ MCP Gateway",
    version=settings.server_version,
)

# Register the initialize handshake handler (TASK-US001-03).
register_initialize_handler(mcp._mcp_server)

# Register the tools/list handler (TASK-US002-01).
register_tools_list_handler(mcp)

# Register the tools/call handler (TASK-US003-01).
register_tools_call_handler(mcp)

# ---------------------------------------------------------------------------
# SSE transport — ASGI app mounted at {mcp_path}/sse in gateway/main.py.
# path="/" places the SSE handshake endpoint at the mount root so the full
# path resolves to  GET {mcp_path}/sse  after FastAPI's app.mount().
# ---------------------------------------------------------------------------
sse_app: StarletteWithLifespan = mcp.http_app(path="/", transport="sse")
