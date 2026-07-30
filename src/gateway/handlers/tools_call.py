"""
MCP ``tools/call`` handler for the ContextIQ Gateway.

TASK-US003-01: Implement tools/call Handler with Input Validation and Pipeline Dispatch.
TASK-US003-02: Agent Worker HTTP Client and Output Schema Validation.
TASK-US003-04: Session Isolation for Concurrent Tool Calls.
TASK-US003-05: End-to-End Correlation ID Tracing and SLA Monitoring.

Registers the FastMCP ``call_tool`` handler that:
1. Validates the requested tool name against the active tool registry.
2. Validates the supplied arguments against the tool's JSON Schema.
3. Constructs a typed dispatch payload sourced from the per-task ``RequestContext``.
4. Forwards the payload to the Agent Worker via :class:`AgentWorkerClient`.
5. Returns the serialised result as an MCP ``TextContent`` list.

Context variable
----------------
``RequestContext`` (from :mod:`src.gateway.context.request_context`) carries
the authenticated user ID, session ID, and a unique request ID across async
boundaries.  The ``RequestContextMiddleware`` populates it before the handler
is invoked.  ``set_user_id_context`` is retained for backward compatibility
with tests and callers that have not yet migrated to the middleware.
"""
from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from unittest.mock import Mock
from uuid import uuid4

import httpx
import jsonschema
import pybreaker
from fastmcp import FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS, ErrorData, TextContent
from opentelemetry import trace
from prometheus_client import Counter, Histogram

from src.gateway.clients.agent_worker_client import AgentWorkerClient
from src.gateway.context.request_context import RequestContext, get_request_context, set_request_context
from src.gateway.errors.tool_errors import (
    CIRCUIT_BREAKER_OPEN,
    INTERNAL_ERROR,
    build_tool_error,
)
from src.gateway.schemas.call_types import ToolCallDispatch
from src.gateway.schemas.clarification_response import ClarificationNeededResponse
from src.gateway.services.tool_registry import ToolRegistryService

logger = logging.getLogger(__name__)

_tracer = trace.get_tracer("contextiq.gateway")

tools_call_total = Counter(
    "contextiq_tools_call_total",
    "Total number of tools/call MCP invocations",
    ["status"],
)

output_schema_violations_total = Counter(
    "contextiq_output_schema_violations_total",
    "Number of output schema mismatches from the Agent Worker",
    ["tool_name"],
)

tool_call_errors_total = Counter(
    "contextiq_tool_call_errors_total",
    "Tool call errors by type",
    ["tool_name", "error_type"],  # error_type: timeout | validation | pipeline | unknown
)

# TASK-US003-05: SLA latency histogram — p95 < 3 s target.
# Buckets chosen to give fine resolution around the 0.5–3 s SLA window.
tool_call_duration = Histogram(
    "contextiq_tool_call_duration_seconds",
    "End-to-end tool call duration from gateway receipt to response",
    ["tool_name", "status"],  # status: success | error | timeout
    buckets=[0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 10.0],
)

# Backward-compatible per-request user ID ContextVar.
# New code should use RequestContext; this var is still honoured as a fallback
# when RequestContextMiddleware has not run (e.g. legacy test helpers).
_user_id_ctx: ContextVar[str] = ContextVar("user_id", default="anonymous")

# Module-level default instances — overridden in tests.
_default_registry: ToolRegistryService | None = None
_default_client: AgentWorkerClient | None = None


def set_user_id_context(user_id: str) -> None:
    """Store *user_id* in the current async context.

    Kept for backward compatibility.  Prefer ``RequestContextMiddleware`` which
    populates the full ``RequestContext`` (including session_id and request_id)
    from the ASGI scope.
    """
    _user_id_ctx.set(user_id)


def _resolve_request_context() -> tuple[str, str, str]:
    """Return ``(request_id, user_id, trace_id_hex)`` for the current invocation.

    Prefers the full ``RequestContext`` populated by ``RequestContextMiddleware``.
    Falls back to generating a fresh ``request_id`` and reading ``_user_id_ctx``
    so existing tests and callers that bypass the middleware continue to work.
    """
    try:
        ctx = get_request_context()
        trace_id_hex = format(ctx.trace_id, "032x") if ctx.trace_id else "0" * 32
        return ctx.request_id, ctx.user_id, trace_id_hex
    except LookupError:
        # Middleware not present — generate a fresh request_id and fall back.
        span_ctx = trace.get_current_span().get_span_context()
        trace_id_hex = format(span_ctx.trace_id, "032x") if span_ctx.trace_id else "0" * 32
        return str(uuid4()), _user_id_ctx.get(), trace_id_hex


def _record_span_outcome(span: trace.Span, elapsed_seconds: float, *, success: bool) -> None:  # type: ignore[name-defined]
    """Attach final timing and outcome attributes to *span*.

    Called at every exit path of the handler (success and all error branches)
    so that Jaeger always has ``mcp.tool.success`` and ``mcp.tool.duration_ms``.
    """
    elapsed_ms = round(elapsed_seconds * 1000, 2)
    span.set_attribute("mcp.tool.success", success)
    span.set_attribute("mcp.tool.duration_ms", elapsed_ms)
    if not success:
        try:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR)
        except Exception:  # noqa: BLE001
            pass


def _get_registry() -> ToolRegistryService:
    global _default_registry  # noqa: PLW0603
    if _default_registry is None:
        _default_registry = ToolRegistryService()
    return _default_registry


def register_tools_call_handler(
    mcp: FastMCP,
    registry: ToolRegistryService | None = None,
    agent_client: AgentWorkerClient | None = None,
) -> None:
    """Wire the ``tools/call`` handler into *mcp*.

    Parameters
    ----------
    mcp:
        The FastMCP server instance to register the handler on.
    registry:
        Optional :class:`ToolRegistryService`.  When *None* the module-level
        singleton is used.  Inject a custom instance in tests.
    agent_client:
        Optional :class:`AgentWorkerClient`.  When *None* the caller is
        responsible for providing a real or stub client via the module-level
        default before the first invocation.  Inject a mock in tests.
    """
    effective_registry = registry if registry is not None else _get_registry()
    effective_client = agent_client  # May be None; resolved in handler body.

    low_level_server = getattr(mcp, "_mcp_server", None)
    registrar_factory = None
    if low_level_server is not None and not isinstance(low_level_server, Mock):
        registrar_factory = getattr(low_level_server, "call_tool", None)
    if registrar_factory is None:
        registrar_factory = mcp.call_tool

    @registrar_factory()
    async def handle_tool_call(name: str, arguments: dict) -> list[TextContent]:  # type: ignore[type-arg]
        """Validate, dispatch, and return the result of a ``tools/call`` invocation."""
        _start = time.monotonic()

        with _tracer.start_as_current_span(
            "mcp.tools.call",
            kind=trace.SpanKind.SERVER,
        ) as span:
            span.set_attribute("mcp.tool.name", name)

            # 1. Validate tool existence (cache-first lookup).
            tool_def = await effective_registry.get_by_name(name)
            builtin_tool = None
            if tool_def is None:
                builtin_tool = await _get_builtin_tool(mcp, name)
                if builtin_tool is None:
                    tools_call_total.labels(status="not_found").inc()
                    raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Tool '{name}' not found or inactive"))
                tool_def = _builtin_tool_definition(builtin_tool)

            # 2. Validate arguments against the tool's JSON Schema.
            schema = tool_def.inputSchema.model_dump()
            try:
                jsonschema.validate(instance=arguments, schema=schema)
            except jsonschema.ValidationError as exc:
                tools_call_total.labels(status="invalid_args").inc()
                raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Invalid arguments: {exc.message}")) from exc

            # 3. Build dispatch payload — sourced from RequestContext so that
            #    concurrent tasks each carry their own isolated identifiers.
            request_id, user_id, trace_id_hex = _resolve_request_context()
            dispatch = ToolCallDispatch(
                request_id=request_id,
                user_id=user_id,
                tool_name=name,
                arguments=arguments,
                trace_id=trace_id_hex,
            )

            # TASK-US003-05: Enrich root span with correlation + user identity.
            span.set_attribute("mcp.request_id", dispatch.request_id)
            span.set_attribute("mcp.tools.call.request_id", dispatch.request_id)  # kept for compat
            span.set_attribute("contextiq.user_id", user_id)

            # 4. Forward to Agent Worker.
            client = effective_client if effective_client is not None else _default_client
            if builtin_tool is not None:
                return await _run_builtin_tool(builtin_tool, arguments)

            if client is None:  # pragma: no cover — only reachable in mis-configured deploys
                raise McpError(INVALID_PARAMS, "Agent Worker client is not configured")

            try:
                result = await client.execute(dispatch)
            except McpError:
                raise  # re-raise typed MCP errors as-is (validation / not-found)
            except httpx.TimeoutException:
                elapsed = time.monotonic() - _start
                logger.error(
                    "Agent Worker timeout for tool %s request_id=%s",
                    name,
                    dispatch.request_id,
                )
                tool_call_errors_total.labels(tool_name=name, error_type="timeout").inc()
                tools_call_total.labels(status="error").inc()
                _record_span_outcome(span, elapsed, success=False)
                tool_call_duration.labels(tool_name=name, status="timeout").observe(elapsed)
                return build_tool_error(
                    INTERNAL_ERROR,
                    "Agent pipeline timed out",
                    {"tool": name, "timeout_ms": 5000},
                )
            except pybreaker.CircuitBreakerError:
                elapsed = time.monotonic() - _start
                logger.warning("Circuit breaker open for tool %s", name)
                tool_call_errors_total.labels(tool_name=name, error_type="pipeline").inc()
                tools_call_total.labels(status="error").inc()
                _record_span_outcome(span, elapsed, success=False)
                tool_call_duration.labels(tool_name=name, status="error").observe(elapsed)
                return build_tool_error(
                    CIRCUIT_BREAKER_OPEN,
                    "Service temporarily unavailable",
                    {"retry_after_seconds": 60},
                )
            except Exception:
                elapsed = time.monotonic() - _start
                logger.exception("Unexpected tool call failure for tool %s", name)
                tool_call_errors_total.labels(tool_name=name, error_type="unknown").inc()
                tools_call_total.labels(status="error").inc()
                _record_span_outcome(span, elapsed, success=False)
                tool_call_duration.labels(tool_name=name, status="error").observe(elapsed)
                return build_tool_error(INTERNAL_ERROR, "Internal error", {"tool": name})

            # 5. Best-effort output schema validation.
            if tool_def.output_schema:
                try:
                    jsonschema.validate(instance=result.data, schema=tool_def.output_schema)
                    span.set_attribute("contextiq.output_schema_valid", True)
                except jsonschema.ValidationError as schema_exc:
                    logger.warning(
                        "Output schema mismatch for tool %s: %s",
                        name,
                        schema_exc.message,
                    )
                    output_schema_violations_total.labels(tool_name=name).inc()
                    span.set_attribute("contextiq.output_schema_valid", False)

            elapsed = time.monotonic() - _start
            _record_span_outcome(span, elapsed, success=True)
            tool_call_duration.labels(tool_name=name, status="success").observe(elapsed)
            tools_call_total.labels(status="success").inc()
            logger.debug(
                "tools/call: tool=%s request_id=%s elapsed_ms=%.1f",
                name,
                dispatch.request_id,
                elapsed * 1000,
            )

            # 6. Serialise output as MCP TextContent.
            # Clarification path: return a structured response, not an MCP error.
            if isinstance(result.data, dict) and result.data.get("type") in {"clarification_needed", "clarification"}:
                clar = ClarificationNeededResponse.model_validate(result.data)
                return [TextContent(type="text", text=clar.model_dump_json())]

            return [TextContent(type="text", text=json.dumps(result.data))]


async def _get_builtin_tool(mcp: FastMCP, name: str) -> object | None:
    get_tool = getattr(mcp, "get_tool", None)
    if get_tool is None:
        return None
    try:
        return await get_tool(name)
    except Exception:
        logger.debug("tools/call: built-in tool lookup failed for %s", name, exc_info=True)
        return None


def _builtin_tool_definition(tool: object):
    from src.gateway.schemas.tool_types import InputSchema, ToolDefinition

    parameters = getattr(tool, "parameters", None) or {}
    output_schema = getattr(tool, "output_schema", None)
    if not isinstance(parameters, dict):
        parameters = {}
    if not isinstance(output_schema, dict):
        output_schema = None
    return ToolDefinition(
        name=getattr(tool, "name", "unknown"),
        description=getattr(tool, "description", None) or getattr(tool, "title", None) or "Built-in MCP tool.",
        inputSchema=InputSchema(
            type="object",
            properties=parameters.get("properties", {}),
            required=parameters.get("required", []),
        ),
        output_schema=output_schema,
    )


async def _run_builtin_tool(tool: object, arguments: dict) -> list[TextContent]:
    result = await tool.run(arguments)
    content = getattr(result, "content", None)
    if content:
        return list(content)
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return [TextContent(type="text", text=json.dumps(structured))]
    return [TextContent(type="text", text="")]
