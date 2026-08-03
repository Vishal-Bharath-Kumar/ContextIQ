"""
Redis-backed cache for the active tool list.

TASK-US002-03: Cache Tool List in Redis with 30-Second Change Propagation.

Provides a read-through cache over the tool_registry table with:
  - TTL of 60 s as a safety-net fallback
  - Invalidation via Redis pub/sub (channel: contextiq:tool_registry:changed)

The cache key stores a JSON-serialised list[ToolDefinition] so the gateway
can serve tools/list from in-memory Redis without hitting PostgreSQL on every
request.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from opentelemetry import trace

from src.gateway.schemas.tool_types import ToolDefinition

logger = logging.getLogger(__name__)


class ToolListCache:
    """Async Redis cache for the active tool definition list.

    Parameters
    ----------
    redis:
        An ``redis.asyncio.Redis`` (or compatible) client instance.
    """

    KEY = "contextiq:tool_registry:active_tools"
    TTL_SECONDS = 60

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def get(self) -> list[ToolDefinition] | None:
        """Return cached tool list, or *None* on cache miss / Redis error."""
        try:
            raw = await self._redis.get(self.KEY)
        except Exception:
            logger.warning("ToolListCache.get failed — Redis unavailable", exc_info=True)
            return None
        current_span = trace.get_current_span()
        if raw is None:
            current_span.set_attribute("contextiq.cache.hit", False)
            return None
        current_span.set_attribute("contextiq.cache.hit", True)
        return [ToolDefinition.model_validate(t) for t in json.loads(raw)]

    async def set(self, tools: list[ToolDefinition]) -> None:
        """Write *tools* to the cache with a 60-second TTL.

        Failures are logged but not re-raised so the service stays operational.
        """
        payload = json.dumps([t.model_dump() for t in tools])
        try:
            await self._redis.set(self.KEY, payload, ex=self.TTL_SECONDS)
        except Exception:
            logger.warning("ToolListCache.set failed — Redis unavailable", exc_info=True)

    async def invalidate(self) -> None:
        """Delete the cache entry so the next read triggers a DB fetch."""
        try:
            await self._redis.delete(self.KEY)
        except Exception:
            logger.warning("ToolListCache.invalidate failed — Redis unavailable", exc_info=True)
