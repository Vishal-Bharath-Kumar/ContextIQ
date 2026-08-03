"""Redis-backed scored model candidate cache (TASK-US019-02).

Stores pre-scored, pre-sorted candidate lists keyed by intent type so the
routing hot-path can skip per-request scoring and satisfy the < 50 ms SLA.
"""

from __future__ import annotations

import json

from redis.asyncio import Redis

from src.model_router.schemas.model_score import ModelScore


class ScoredModelCache:
    """Redis cache of pre-scored model candidate lists, keyed per intent type.

    Key schema: ``contextiq:model_router:scored:{intent_type}``
    TTL:        30 seconds (short; invalidated when the model list changes)
    """

    KEY_PREFIX: str = "contextiq:model_router:scored"
    TTL_SECONDS: int = 30

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key(self, intent_type: str) -> str:
        return f"{self.KEY_PREFIX}:{intent_type}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, intent_type: str) -> list[ModelScore] | None:
        """Return cached scored list or ``None`` on cache miss."""
        raw = await self._redis.get(self._key(intent_type))
        if raw is None:
            return None
        return [ModelScore.model_validate(item) for item in json.loads(raw)]

    async def set(self, intent_type: str, scores: list[ModelScore]) -> None:
        """Serialise *scores* and write to Redis with a 30-second TTL."""
        payload = json.dumps([s.model_dump(mode="json") for s in scores])
        await self._redis.set(self._key(intent_type), payload, ex=self.TTL_SECONDS)

    async def invalidate(self, intent_type: str) -> None:
        """Delete the cached entry for a single intent type."""
        await self._redis.delete(self._key(intent_type))

    async def invalidate_all(self) -> None:
        """Delete all scored-cache entries.

        Uses ``SCAN`` (not ``KEYS``) to avoid blocking the Redis event loop
        when a large number of intent-type keys exist.
        """
        pattern = f"{self.KEY_PREFIX}:*"
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self._redis.delete(*keys)
            if cursor == 0:
                break
