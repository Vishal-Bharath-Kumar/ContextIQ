"""
MCP tool-list type schemas for the ContextIQ Gateway.

TASK-US002-01: Implement tools/list MCP Handler.
TASK-US003-02: Agent Worker HTTP Client and Output Schema Validation.

Defines Pydantic models that represent the MCP ``tools/list`` response payload.
All models conform to the MCP 2024-11-05 protocol specification.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class InputSchema(BaseModel):
    """JSON Schema object describing a tool's accepted input."""

    type: Literal["object"] = "object"
    properties: dict[str, dict] = {}  # noqa: RUF012
    required: list[str] = []  # noqa: RUF012


class ToolDefinition(BaseModel):
    """A single registered tool exposed via the MCP ``tools/list`` response."""

    name: str
    description: str
    inputSchema: InputSchema = InputSchema()
    output_schema: dict[str, Any] | None = None


class ToolListResult(BaseModel):
    """Top-level ``tools/list`` response payload."""

    tools: list[ToolDefinition] = []  # noqa: RUF012
    cache_hit: bool = False
