"""Redis-backed cache for the active model list.

TASK-US018-04: POST /v1/models and GET /v1/models API Endpoints.

Provides a read-through cache over the model_registry table with:
  - TTL of 60 s as a safety-net fallback
  - Invalidation via Redis pub/sub (channel: contextiq:model_registry:changed)

The cache key stores a JSON-serialised list[ModelDefinition] so the GET
handler can serve active models from Redis without hitting PostgreSQL on
every request.
"""
from __future__ import annotations

import json
import logging

from opentelemetry import trace
from redis.asyncio import Redis

from src.model_registry.schemas.model_definition import ModelDefinition

logger = logging.getLogger(__name__)


class ModelListCache:
    """Async Redis cache for the active model definition list.

    Parameters
    ----------
    redis:
        An ``redis.asyncio.Redis`` (or compatible) client instance.
    """

    KEY = "contextiq:model_registry:active_models"
    TTL_SECONDS = 60

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self) -> list[ModelDefinition] | None:
        """Return cached model list, or *None* on cache miss / Redis error."""
        try:
            raw = await self._redis.get(self.KEY)
        except Exception:
            logger.warning("ModelListCache.get failed — Redis unavailable", exc_info=True)
            return None
        current_span = trace.get_current_span()
        if raw is None:
            current_span.set_attribute("contextiq.cache.hit", False)
            return None
        current_span.set_attribute("contextiq.cache.hit", True)
        return [ModelDefinition.model_validate(m) for m in json.loads(raw)]

    async def set(self, models: list[ModelDefinition]) -> None:
        """Write *models* to the cache with a 60-second TTL.

        Failures are logged but not re-raised so the service stays operational.
        """
        payload = json.dumps([m.model_dump(mode="json") for m in models])
        try:
            await self._redis.set(self.KEY, payload, ex=self.TTL_SECONDS)
        except Exception:
            logger.warning("ModelListCache.set failed — Redis unavailable", exc_info=True)

    async def invalidate(self) -> None:
        """Delete the cache entry so the next read triggers a DB fetch."""
        try:
            await self._redis.delete(self.KEY)
        except Exception:
            logger.warning("ModelListCache.invalidate failed — Redis unavailable", exc_info=True)
