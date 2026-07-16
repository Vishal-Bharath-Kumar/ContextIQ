"""Pydantic schemas for the Agent Worker ``POST /v1/execute`` endpoint.

TASK-US005-02: Implement ``POST /v1/execute`` Entrypoint and Initial State Hydration.

Models
------
ToolCallError   — structured error payload included in ``ExecuteResponse`` on failure.
ExecuteRequest  — validated dispatch payload received from the MCP Gateway.
ExecuteResponse — response envelope returned to the MCP Gateway for every invocation.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DegradedSourceSummary(BaseModel):
    """Summary of a connector that failed during the pipeline execution."""

    source_id: str = Field(..., description="Connector source identifier (e.g. 'jira:myproject').")
    error_type: str = Field(..., description="Exception class name (e.g. 'ConnectorTimeoutError').")
    message: str = Field(..., description="Human-readable failure description.")


class ToolCallError(BaseModel):
    """Structured error payload for JSON-RPC style error codes."""

    code: int = Field(..., description="JSON-RPC error code (e.g. -32603 for internal error).")
    message: str = Field(..., description="Human-readable error description.")
    data: dict[str, Any] | None = Field(None, description="Structured error details (e.g. failed_node, error_type, timestamp).")


class ExecuteRequest(BaseModel):
    """Dispatch payload forwarded from the MCP Gateway to ``POST /v1/execute``."""

    request_id: str = Field(..., description="UUID v4 — used as LangGraph thread_id.")
    user_id: str = Field(..., description="Authenticated user identifier from JWT sub claim.")
    username: str = Field(default="", description="Authenticated username.")
    roles: list[str] = Field(default_factory=list, description="User role list from JWT.")
    tool_name: str = Field(..., description="Registered MCP tool name that triggered this request.")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Raw MCP tool arguments."
    )
    trace_id: str = Field(..., description="W3C traceparent trace ID propagated from the gateway.")


class ExecuteResponse(BaseModel):
    """Response envelope returned to the MCP Gateway for every invocation.

    The Agent Worker always returns HTTP 200 with a structured response — even on
    pipeline failure — so the gateway always receives a typed payload.
    """

    request_id: str = Field(..., description="Echoed request ID for correlation.")
    status: Literal["success", "error"] = Field(..., description="Execution outcome.")
    output: dict[str, Any] | None = Field(None, description="Populated on success.")
    error: ToolCallError | None = Field(None, description="Populated on error.")
    duration_ms: int = Field(..., description="Wall-clock execution time in milliseconds.")
