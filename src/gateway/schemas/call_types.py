"""
Pydantic schemas for the MCP ``tools/call`` pipeline.

TASK-US003-01: Implement tools/call Handler with Input Validation and Pipeline Dispatch.
TASK-US003-02: Agent Worker HTTP Client and Output Schema Validation.

Models
------
ToolCallRequest     — inbound ``tools/call`` arguments from the AI assistant.
ToolCallDispatch    — payload forwarded to the Agent Worker ``POST /v1/execute``.
ToolCallOutput      — successful tool execution payload (nested in AgentWorkerResponse).
ToolCallError       — error detail returned by the Agent Worker.
AgentWorkerResponse — full response envelope from the Agent Worker.
ToolCallResponse    — legacy response model (kept for backward compatibility).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DegradedSourceSummary(BaseModel):
    """Summary of a connector degradation surfaced to the MCP caller."""

    source_id: str = Field(..., description="Connector source identifier (e.g. 'jira:myproject').")
    error_type: str = Field(..., description="Exception class name for the degraded connector.")
    message: str = Field(..., description="Human-readable degradation summary.")


class ToolCallRequest(BaseModel):
    """Represents the inbound ``tools/call`` request from an AI assistant."""

    name: str = Field(..., description="Registered tool name.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool input arguments.")


class ToolCallDispatch(BaseModel):
    """Payload forwarded to the Agent Worker ``POST /v1/execute``."""

    request_id: str = Field(..., description="Unique UUID v4 for this invocation.")
    user_id: str = Field(..., description="Authenticated user identifier from JWT.")
    tool_name: str = Field(..., description="Registered tool name.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Validated tool input arguments.")
    trace_id: str = Field(..., description="OTel trace ID of the current span context (32-char hex).")


class ToolCallOutput(BaseModel):
    """Successful tool execution payload returned by the Agent Worker."""

    data: dict[str, Any] | list[Any] | str = Field(..., description="Tool-specific output payload.")
    degraded_sources: list[DegradedSourceSummary] = Field(
        default_factory=list,
        description="Connectors that degraded during execution while the tool still completed.",
    )
    output_schema_version: str = Field("1.0", description="Version of the output schema contract.")


class ToolCallError(BaseModel):
    """Error detail returned by the Agent Worker on failure."""

    code: str = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="Human-readable error description.")
    details: dict[str, Any] | None = Field(None, description="Optional structured error context.")


class AgentWorkerResponse(BaseModel):
    """Full response envelope from the Agent Worker ``POST /v1/execute``."""

    request_id: str = Field(..., description="Echoed request ID for correlation.")
    status: Literal["success", "error"] = Field(..., description="Execution status.")
    output: ToolCallOutput | None = Field(None, description="Populated on success.")
    error: ToolCallError | None = Field(None, description="Populated on error.")
    duration_ms: int = Field(..., description="Wall-clock execution time in milliseconds.")


class ToolCallResponse(BaseModel):
    """Legacy response model — kept for backward compatibility with TASK-US003-01 tests."""

    request_id: str = Field(..., description="Echoed request ID for correlation.")
    output: Any = Field(..., description="Tool execution output (any JSON-serialisable value).")
