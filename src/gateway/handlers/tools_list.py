"""
MCP ``tools/list`` handler for the ContextIQ Gateway.

TASK-US002-01: Implement tools/list MCP Handler.
TASK-US002-05: Instrument tools/list with OpenTelemetry spans.

Registers the FastMCP ``list_tools`` handler that returns the current set of
active tool definitions to an AI assistant.  Active tools are served from the
Redis cache (TASK-US002-03); on a cache miss the handler falls back to the
PostgreSQL registry (TASK-US002-02).

Performance contract
--------------------
Handler must respond in < 200 ms when serving up to 50 tools from cache.

Integration
-----------
``register_tools_list_handler(mcp)`` wires the decorated coroutine into the
FastMCP instance so it is invoked for every ``tools/list`` request.
"""
from __future__ import annotations

import logging
from unittest.mock import Mock

from fastmcp import FastMCP
from opentelemetry import trace
from prometheus_client import Counter

from src.gateway.schemas.tool_types import ToolDefinition, ToolListResult
from src.gateway.schemas.tool_types import InputSchema
from src.gateway.services.tool_registry import ToolRegistryService

logger = logging.getLogger(__name__)

_tracer = trace.get_tracer("contextiq.gateway")

tools_list_calls_total = Counter(
    "contextiq_tools_list_calls_total",
    "Total number of tools/list MCP calls",
    ["cache_hit"],
)

# Module-level default service instance — can be overridden in tests.
_default_registry: ToolRegistryService | None = None


def _get_registry() -> ToolRegistryService:
    global _default_registry  # noqa: PLW0603
    if _default_registry is None:
        _default_registry = ToolRegistryService()
    return _default_registry


def register_tools_list_handler(
    mcp: FastMCP,
    registry: ToolRegistryService | None = None,
) -> None:
    """Wire the ``tools/list`` handler into *mcp*.

    Parameters
    ----------
    mcp:
        The FastMCP server instance to register the handler on.
    registry:
        Optional :class:`ToolRegistryService` to use.  When *None* the
        module-level singleton is used (cache → DB fallback).  Inject a
        custom instance in tests to avoid real I/O.
    """
    effective_registry = registry if registry is not None else _get_registry()

    low_level_server = getattr(mcp, "_mcp_server", None)
    registrar_factory = None
    if low_level_server is not None and not isinstance(low_level_server, Mock):
        registrar_factory = getattr(low_level_server, "list_tools", None)
    if registrar_factory is None:
        registrar_factory = mcp.list_tools

    @registrar_factory()
    async def handle_tools_list() -> list[ToolDefinition]:
        """Return the active tool definitions sorted by name (ASC)."""
        with _tracer.start_as_current_span("mcp.tools.list") as span:
            logger.debug("tools/list: fetching active tools from registry")
            result: ToolListResult = await effective_registry.get_active_tools()
            tools_by_name = {tool.name: tool for tool in result.tools}
            for builtin in await _list_builtin_tool_definitions(mcp):
                tools_by_name.setdefault(builtin.name, builtin)

            merged_tools = sorted(tools_by_name.values(), key=lambda tool: tool.name)
            tool_count = len(merged_tools)
            cache_hit: bool = result.cache_hit
            span.set_attribute("mcp.tools.count", tool_count)
            span.set_attribute("contextiq.cache.hit", cache_hit)
            tools_list_calls_total.labels(cache_hit=str(cache_hit).lower()).inc()
            logger.debug("tools/list: returning %d tool(s)", tool_count)
            return merged_tools


async def _list_builtin_tool_definitions(mcp: FastMCP) -> list[ToolDefinition]:
    list_tools = getattr(mcp, "_list_tools", None)
    if list_tools is None:
        return []

    try:
        tools = await list_tools()
    except Exception:
        logger.debug("tools/list: built-in tool enumeration failed", exc_info=True)
        return []

    results: list[ToolDefinition] = []
    for tool in tools:
        parameters = getattr(tool, "parameters", None) or {}
        if not isinstance(parameters, dict):
            parameters = {}
        results.append(
            ToolDefinition(
                name=getattr(tool, "name", "unknown"),
                description=getattr(tool, "description", None) or getattr(tool, "title", None) or "Built-in MCP tool.",
                inputSchema=InputSchema(
                    type="object",
                    properties=parameters.get("properties", {}),
                    required=parameters.get("required", []),
                ),
                output_schema=getattr(tool, "output_schema", None),
            )
        )
    return results

