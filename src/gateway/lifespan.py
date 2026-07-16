"""
Redis pub/sub invalidation subscriber for the tool list cache.

TASK-US002-03: Subscribes to ``contextiq:tool_registry:changed`` and calls
:meth:`ToolListCache.invalidate` so that stale cache entries are evicted
within the 30-second change-propagation SLA.

Usage
-----
Start the subscriber inside the FastAPI ``lifespan`` context::

    from src.gateway.lifespan import start_cache_invalidation_subscriber

    async with asynccontextmanager(lifespan)(app):
        task = asyncio.create_task(
            start_cache_invalidation_subscriber(redis, cache)
        )
        yield
        task.cancel()
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.registry.cache.tool_cache import ToolListCache

logger = logging.getLogger(__name__)

_PUBSUB_CHANNEL = "contextiq:tool_registry:changed"


async def _subscribe_invalidation(redis: Any, cache: ToolListCache) -> None:
    """Subscribe to the tool-registry change channel and invalidate on message.

    Runs indefinitely until cancelled.  Reconnects automatically on transient
    Redis errors (backoff: 2 s) so a short Redis blip does not kill the task.
    """
    while True:
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(_PUBSUB_CHANNEL)
            logger.info(
                "Cache invalidation subscriber started on channel '%s'",
                _PUBSUB_CHANNEL,
            )
            async for message in pubsub.listen():
                if message["type"] == "message":
                    logger.debug(
                        "Cache invalidation triggered by pub/sub message: %s",
                        message.get("data"),
                    )
                    await cache.invalidate()
        except asyncio.CancelledError:
            logger.info("Cache invalidation subscriber shutting down")
            raise
        except Exception:
            logger.warning(
                "Cache invalidation subscriber error — reconnecting in 2 s",
                exc_info=True,
            )
            await asyncio.sleep(2)


async def start_cache_invalidation_subscriber(
    redis: Any,
    cache: ToolListCache,
) -> None:
    """Entry point launched as an asyncio task from the gateway lifespan."""
    await _subscribe_invalidation(redis, cache)


async def start_indexing_consumer(consumer: Any) -> None:  # noqa: ANN401
    """Entry point launched as an asyncio task from the gateway lifespan.

    Calls ``consumer.start()`` then blocks inside ``consumer.run()`` until
    the consumer is stopped or the task is cancelled.
    """
    try:
        await consumer.start()
        await consumer.run()
    except asyncio.CancelledError:
        logger.info("Indexing consumer task cancelled — shutting down")
        raise
    except Exception:
        logger.exception("Indexing consumer task raised an unexpected error")
