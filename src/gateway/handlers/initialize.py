"""
MCP ``initialize`` handshake handler.

TASK-US001-03: Implement MCP initialize Handshake Handler.

This module defines ``handle_initialize`` — the function that processes the
first message in every MCP session.  It validates the client's requested
protocol version, logs the connecting client identity, and returns the
server's negotiated version, identity, and capability advertisement.

JSON-RPC error codes used
--------------------------
-32700  Parse error   — ``clientInfo`` fields missing / request malformed.
-32600  Invalid Request — ``protocolVersion`` not in the supported set.

Integration
-----------
``register_initialize_handler(mcp_server)`` wires ``handle_initialize`` into
the underlying ``mcp.server.lowlevel.Server`` request-handler registry so
that it is invoked for every ``InitializeRequest`` dispatched by FastMCP.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp import types as mcp_types
from mcp.server.lowlevel import Server as LowLevelServer
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from src.gateway.config import settings
from src.gateway.schemas.mcp_types import (
    ClientInfo,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
    ServerInfo,
)
from src.gateway.telemetry import get_tracer, get_transport_context

logger = logging.getLogger(__name__)

# Protocol versions this gateway explicitly supports.
SUPPORTED_PROTOCOL_VERSIONS: list[str] = ["2024-11-05"]


# ---------------------------------------------------------------------------
# Core handler
# ---------------------------------------------------------------------------

async def handle_initialize(request: InitializeRequest) -> InitializeResult:
    """
    Process a validated MCP ``initialize`` request.

    Parameters
    ----------
    request:
        Validated ``InitializeRequest`` instance.

    Returns
    -------
    InitializeResult
        Contains the negotiated protocol version, gateway identity, and
        capability advertisement.

    Raises
    ------
    McpError (code -32600)
        When ``request.protocolVersion`` is not in ``SUPPORTED_PROTOCOL_VERSIONS``.
    """
    if request.protocolVersion not in SUPPORTED_PROTOCOL_VERSIONS:
        raise McpError(
            mcp_types.ErrorData(
                code=-32600,
                message=(
                    f"Unsupported protocolVersion: {request.protocolVersion!r}. "
                    f"Supported: {SUPPORTED_PROTOCOL_VERSIONS}"
                ),
            )
        )

    tracer = get_tracer()
    transport = get_transport_context()

    with tracer.start_as_current_span("mcp.initialize") as span:
        span.set_attribute("mcp.protocol_version", request.protocolVersion)
        span.set_attribute("mcp.client.name", request.clientInfo.name)
        span.set_attribute("mcp.transport", transport)

        logger.info(
            "MCP initialize: client=%r version=%r",
            request.clientInfo.name,
            request.clientInfo.version,
        )

        return InitializeResult(
            protocolVersion=request.protocolVersion,
            serverInfo=ServerInfo(
                name="ContextIQ MCP Gateway",
                version=settings.server_version,
            ),
            capabilities=ServerCapabilities(),
        )


# ---------------------------------------------------------------------------
# Low-level server registration
# ---------------------------------------------------------------------------

def register_initialize_handler(low_level_server: LowLevelServer) -> None:
    """
    Wire ``handle_initialize`` into *low_level_server*'s request-handler
    registry.

    The wrapper function:
    1. Parses the raw ``mcp.types.InitializeRequest`` params into our typed
       ``InitializeRequest`` model (raises ``McpError -32700`` on parse
       failure).
    2. Delegates to ``handle_initialize`` for version validation and logging.
    3. Translates the ``InitializeResult`` back into the SDK's
       ``mcp.types.InitializeResult`` so the transport layer can serialise it.

    Parameters
    ----------
    low_level_server:
        The ``mcp.server.lowlevel.Server`` instance (accessible as
        ``fastmcp_instance._mcp_server``).
    """

    async def _handler(sdk_request: mcp_types.InitializeRequest) -> Any:  # noqa: ANN401
        params = sdk_request.params

        # -- Parse / validate --------------------------------------------------
        try:
            request = InitializeRequest(
                protocolVersion=params.protocolVersion,
                clientInfo=ClientInfo(
                    name=params.clientInfo.name,
                    version=params.clientInfo.version,
                ),
                capabilities=params.capabilities.model_dump()
                if params.capabilities
                else {},
            )
        except ValidationError as exc:
            raise McpError(
                mcp_types.ErrorData(
                    code=-32700,
                    message=f"Parse error: {exc}",
                )
            ) from exc

        # -- Delegate to validated handler ------------------------------------
        result = await handle_initialize(request)

        # -- Translate back to SDK types --------------------------------------
        return mcp_types.ServerResult(
            mcp_types.InitializeResult(
                protocolVersion=result.protocolVersion,
                serverInfo=mcp_types.Implementation(
                    name=result.serverInfo.name,
                    version=result.serverInfo.version,
                ),
                capabilities=mcp_types.ServerCapabilities(
                    tools=mcp_types.ToolsCapability(
                        listChanged=result.capabilities.tools.get("listChanged", True),
                    ),
                ),
            )
        )

    low_level_server.request_handlers[mcp_types.InitializeRequest] = _handler
