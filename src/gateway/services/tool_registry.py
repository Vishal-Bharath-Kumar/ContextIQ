"""
Tool registry service for the ContextIQ Gateway.

TASK-US002-03: Implements the read-through cache pattern over the tool registry.

Lookup order
------------
1. Redis cache (fast path — ToolListCache)
2. PostgreSQL registry (ToolRepository via SQLAlchemy)
3. Empty list (no tools registered / both unavailable)
"""
from __future__ import annotations

import logging
from typing import Any

from src.gateway.schemas.tool_types import InputSchema, ToolDefinition, ToolListResult
from src.registry.cache.tool_cache import ToolListCache

logger = logging.getLogger(__name__)


class ToolRegistryService:
    """Provides active tool definitions to MCP handlers with Redis caching.

    Parameters
    ----------
    cache:
        :class:`~src.registry.cache.tool_cache.ToolListCache` instance.
        When *None*, cache lookups are skipped (falls through to *repo*).
    repo:
        An async repository with a ``find_active()`` coroutine that returns
        ORM tool objects.  When *None*, the DB path is skipped and the
        service returns an empty list.
    """

    def __init__(
        self,
        cache: ToolListCache | None = None,
        repo: Any | None = None,
    ) -> None:
        self._cache = cache
        self._repo = repo

    async def get_active_tools(self) -> ToolListResult:
        """Return all active tools using the read-through cache pattern.

        1. Check Redis cache — return immediately on hit.
        2. On miss, query the DB repository.
        3. Write DB result back to cache.
        4. If both paths fail, return an empty result (never raises).
        """
        # --- Cache fast path ---
        if self._cache is not None:
            cached = await self._cache.get()
            if cached is not None:
                logger.debug("tools/list: cache hit (%d tools)", len(cached))
                return ToolListResult(tools=cached, cache_hit=True)

        # --- DB fallback ---
        tools: list[ToolDefinition] = []
        if self._repo is not None:
            try:
                db_tools = await self._repo.find_active()
                tools = [
                    ToolDefinition(
                        name=t.name,
                        description=t.description,
                        inputSchema=InputSchema(
                            type="object",
                            properties=t.input_schema.get("properties", {}),
                            required=t.input_schema.get("required", []),
                        ),
                    )
                    for t in db_tools
                ]
            except Exception:
                logger.warning(
                    "tools/list: DB query failed — returning empty list",
                    exc_info=True,
                )
                return ToolListResult(tools=[])

        # Write to cache for subsequent requests
        if self._cache is not None and tools:
            await self._cache.set(tools)

        logger.debug("tools/list: DB path (%d tools)", len(tools))
        return ToolListResult(tools=tools)

    async def get_by_name(self, name: str) -> ToolDefinition | None:
        """Return the active :class:`ToolDefinition` for *name*, or ``None``.

        Uses the cached tool list as the primary lookup to avoid extra DB
        round-trips on every ``tools/call`` invocation.
        """
        result = await self.get_active_tools()
        for tool in result.tools:
            if tool.name == name:
                return tool
        return None
