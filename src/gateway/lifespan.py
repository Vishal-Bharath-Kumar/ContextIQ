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


async def setup_neo4j_entity_store(app: Any) -> None:  # noqa: ANN401
    """Initialise ``Neo4jEntityStore`` and attach it to ``app.state``.

    Creates uniqueness constraints for all entity type labels (idempotent) and
    stores the driver on ``app.state.neo4j_store`` so route handlers can
    retrieve it without re-constructing the driver on each request.

    Call during lifespan startup::

        await setup_neo4j_entity_store(app)

    Call during lifespan shutdown::

        await app.state.neo4j_store.close()
    """
    from src.knowledge_graph.stores.neo4j_store import Neo4jEntityStore

    store = Neo4jEntityStore()
    await store.apply_constraints()
    app.state.neo4j_store = store
    logger.info("Neo4jEntityStore initialised and constraints applied")


async def start_entity_consumer(consumer: Any) -> None:  # noqa: ANN401
    """Entry point launched as an asyncio task from the gateway lifespan.

    Calls ``consumer.start()`` then blocks inside ``consumer.run()`` until
    the consumer is stopped or the task is cancelled.
    """
    try:
        await consumer.start()
        await consumer.run()
    except asyncio.CancelledError:
        logger.info("Entity consumer task cancelled — shutting down")
        raise
    except Exception:
        logger.exception("Entity consumer task raised an unexpected error")


async def start_graph_updater_consumer(consumer: Any) -> None:  # noqa: ANN401
    """Entry point launched as an asyncio task from the gateway lifespan.

    Starts the ``GraphUpdaterConsumer`` then blocks inside ``consumer.run()``
    until the consumer is stopped or the task is cancelled.
    """
    try:
        await consumer.start()
        await consumer.run()
    except asyncio.CancelledError:
        logger.info("Graph updater consumer task cancelled — shutting down")
        raise
    except Exception:
        logger.exception("Graph updater consumer task raised an unexpected error")


async def start_policy_hot_reloader(app: Any) -> None:  # noqa: ANN401
    """Start the ``PolicyHotReloader`` background task and attach it to ``app.state``.

    The reloader polls the OPA sidecar status endpoint every
    ``poll_interval_s`` seconds (default 30 s) and updates
    ``app.state.bundle_info`` when a new bundle revision is detected,
    satisfying AC-6 (≤ 60 s propagation without platform restart).

    Call during lifespan startup after ``PolicyBundleLoader.verify()``::

        await start_policy_hot_reloader(app)

    Call during lifespan shutdown::

        app.state.hot_reloader.stop()
        app.state.hot_reloader_task.cancel()
    """
    from src.governance.opa.hot_reloader import HotReloadSettings, PolicyHotReloader

    settings = HotReloadSettings()
    hot_reloader = PolicyHotReloader(app.state.bundle_info, settings)

    def _sync_bundle_to_app_state() -> None:
        app.state.bundle_info = hot_reloader.current_bundle

    hot_reloader.on_reload(_sync_bundle_to_app_state)

    task = asyncio.create_task(hot_reloader.run(), name="policy_hot_reloader")
    app.state.hot_reloader = hot_reloader
    app.state.hot_reloader_task = task
    logger.info("PolicyHotReloader task created (poll_interval=%ss)", settings.poll_interval_s)
