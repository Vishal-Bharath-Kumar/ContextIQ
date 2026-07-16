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

from opentelemetry import trace
from prometheus_client import Counter

from fastmcp import FastMCP

from src.gateway.schemas.tool_types import ToolDefinition, ToolListResult
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

    @mcp.list_tools()
    async def handle_tools_list() -> list[ToolDefinition]:
        """Return the active tool definitions sorted by name (ASC)."""
        with _tracer.start_as_current_span("mcp.tools.list") as span:
            logger.debug("tools/list: fetching active tools from registry")
            result: ToolListResult = await effective_registry.get_active_tools()
            tool_count = len(result.tools)
            cache_hit: bool = result.cache_hit
            span.set_attribute("mcp.tools.count", tool_count)
            span.set_attribute("contextiq.cache.hit", cache_hit)
            tools_list_calls_total.labels(cache_hit=str(cache_hit).lower()).inc()
            logger.debug("tools/list: returning %d tool(s)", tool_count)
            return result.tools

