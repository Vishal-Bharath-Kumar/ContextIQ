"""Async Redis cache store for context retrieval results.

TASK-US013-02: Implements ContextCacheStore, which serialises and
deserialises list[RetrievedChunk] with a configurable per-source TTL.
The store is the low-level I/O layer; cache-aside orchestration lives in
the wrapper (TASK-US013-03).
"""

from __future__ import annotations

import json

from redis.asyncio import Redis

from src.retrieval.cache.cache_key import ContextCacheKey, redis_key
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

# Default TTL by source type (seconds). Configurable via settings overlay.
TTL_CONFIG: dict[str, int] = {
    # Code sources — changes frequently during active development
    "github":        5 * 60,    # 5 minutes
    "gitlab":        5 * 60,

    # Documentation and wiki sources — updated less frequently
    "confluence":   30 * 60,    # 30 minutes
    "notion":       30 * 60,
    "miro":         30 * 60,    # design tool — changes at documentation pace

    # Observability — metrics data is time-series; short TTL
    "grafana":       2 * 60,    # 2 minutes
    "datadog":       2 * 60,
    "pagerduty":     2 * 60,

    # Ticket trackers — moderate change rate
    "jira":         10 * 60,    # 10 minutes
    "stackoverflow": 60 * 60,   # 60 minutes — external, rarely changes
}
DEFAULT_TTL: int = 10 * 60  # fallback for unregistered source types


def assert_ttl_coverage(required_source_ids: set[str]) -> None:
    """Assert TTL_CONFIG covers all required source IDs.

    Call at application startup to fail fast when SOURCE_MAP references
    sources without an explicit TTL entry.

    Args:
        required_source_ids: Set of source IDs that must appear in TTL_CONFIG.

    Raises:
        AssertionError: when any required source ID is missing from TTL_CONFIG.
    """
    missing = required_source_ids - TTL_CONFIG.keys()
    assert not missing, (
        f"TTL_CONFIG is missing entries for source IDs: {sorted(missing)}. "
        "Add an explicit TTL to TTL_CONFIG or remove the startup assertion."
    )


class ContextCacheStore:
    """Async Redis adapter for serialising/deserialising list[RetrievedChunk].

    Per-source TTL is resolved from ``ttl_config``; unknown sources fall
    back to ``DEFAULT_TTL``.  SCAN-based bulk deletion prevents blocking
    the Redis event loop on large keyspaces.
    """

    def __init__(
        self,
        redis: Redis,
        ttl_config: dict[str, int] = TTL_CONFIG,
    ) -> None:
        self._redis = redis
        self._ttl_config = ttl_config

    async def get(self, key: ContextCacheKey) -> list[RetrievedChunk] | None:
        """Return cached chunks, or None on cache miss."""
        raw = await self._redis.get(redis_key(key))
        if raw is None:
            return None
        data = json.loads(raw)
        return [RetrievedChunk.model_validate(item) for item in data]

    async def set(
        self,
        key: ContextCacheKey,
        chunks: list[RetrievedChunk],
    ) -> None:
        """Serialise and store chunks with the source-appropriate TTL."""
        ttl = self._ttl_config.get(key.source_id, DEFAULT_TTL)
        payload = json.dumps([c.model_dump(mode="json") for c in chunks])
        await self._redis.set(redis_key(key), payload, ex=ttl)

    async def invalidate_source(self, source_id: str) -> int:
        """Delete all cache entries for a given source. Returns count deleted.

        Uses SCAN with count=100 to avoid blocking the Redis event loop on
        large keyspaces. Keys are deleted one at a time to prevent multi-key
        DEL from becoming a blocking operation.
        """
        pattern = f"ctx_cache:{source_id}:*"
        deleted = 0
        async for key_bytes in self._redis.scan_iter(match=pattern, count=100):
            await self._redis.delete(key_bytes)
            deleted += 1
        return deleted
