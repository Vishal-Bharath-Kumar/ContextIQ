"""
MCP protocol type schemas for the ContextIQ Gateway.

TASK-US001-03: Implement MCP initialize Handshake Handler.

Defines Pydantic models for the MCP initialize request / response cycle.
These types are the gateway's own validated layer on top of the raw protocol
so that handlers can operate on clean, typed data regardless of transport.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ClientInfo(BaseModel):
    """Identifies the connecting MCP client."""

    name: str
    version: str

    @field_validator("name", "version")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field must not be empty")
        return v


class InitializeRequest(BaseModel):
    """
    Validated payload of an MCP ``initialize`` message.

    ``protocolVersion`` must be one of the values in
    ``SUPPORTED_PROTOCOL_VERSIONS`` declared in the handler module.
    ``capabilities`` is optional; defaults to an empty mapping when omitted.
    """

    protocolVersion: str
    clientInfo: ClientInfo
    capabilities: dict[str, object] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ServerInfo(BaseModel):
    """Gateway identity returned in the ``initialize`` response."""

    name: str
    version: str


def _default_tools_cap() -> dict[str, object]:
    return {"listChanged": True}


class ServerCapabilities(BaseModel):
    """
    Gateway capability advertisement.

    ``tools.listChanged`` signals that the server will push
    ``notifications/tools/list_changed`` events when the tool set changes.
    """

    tools: dict[str, object] = Field(default_factory=_default_tools_cap)


class InitializeResult(BaseModel):
    """
    MCP ``initialize`` response payload.

    ``protocolVersion`` echoes the negotiated version.
    ``serverInfo`` carries the gateway identity.
    ``capabilities`` advertises the supported feature set.
    """

    protocolVersion: str = "2024-11-05"
    serverInfo: ServerInfo
    capabilities: ServerCapabilities = Field(default_factory=ServerCapabilities)
