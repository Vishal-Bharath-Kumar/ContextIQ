"""Kafka consumer that invalidates the context cache on source sync events.

TASK-US013-05: Subscribes to the ``contextiq.source.sync`` topic and calls
``ContextCacheStore.invalidate_source()`` whenever EP-008 signals that a
source's document index has been refreshed.

At-least-once delivery
----------------------
``enable_auto_commit=False`` paired with a manual ``commit()`` after each
successful invalidation guarantees that a pod crash mid-flush causes the
event to be reprocessed on restart.  ``invalidate_source`` is idempotent, so
redelivery is safe.

Poison-pill protection
----------------------
Any exception during message handling is caught, logged, and skipped so that
a malformed message never stalls the consume loop.
"""
from __future__ import annotations

import asyncio
import json

import structlog
from aiokafka import AIOKafkaConsumer

from src.retrieval.cache.cache_store import ContextCacheStore
from src.retrieval.cache.sync_event_schema import SourceSyncEvent

log = structlog.get_logger()


class SourceSyncEventConsumer:
    """Kafka consumer that purges cache entries when a source is re-indexed.

    Usage
    -----
    ::

        consumer = SourceSyncEventConsumer(cache=store, bootstrap_servers="localhost:9092")
        await consumer.start()
        task = asyncio.create_task(consumer.consume())
        # … on shutdown …
        task.cancel()
        await consumer.stop()
    """

    TOPIC: str = "contextiq.source.sync"
    CONSUMER_GROUP: str = "context-cache-invalidator"

    def __init__(self, cache: ContextCacheStore, bootstrap_servers: str) -> None:
        self._cache = cache
        self._consumer = AIOKafkaConsumer(
            self.TOPIC,
            bootstrap_servers=bootstrap_servers,
            group_id=self.CONSUMER_GROUP,
            value_deserializer=lambda v: json.loads(v.decode()),
            auto_offset_reset="latest",   # only process new sync events
            enable_auto_commit=False,     # manual commit after successful invalidation
        )

    async def start(self) -> None:
        """Connect to Kafka and subscribe to the sync topic."""
        await self._consumer.start()

    async def stop(self) -> None:
        """Flush pending offsets and close the Kafka connection."""
        await self._consumer.stop()

    async def consume(self) -> None:
        """Blocking consume loop — run as a background :func:`asyncio.create_task`."""
        async for msg in self._consumer:
            try:
                event = SourceSyncEvent.model_validate(msg.value)
                deleted = await self._cache.invalidate_source(event.source_id)
                log.info(
                    "cache_invalidated_on_sync",
                    source_id=event.source_id,
                    sync_type=event.sync_type,
                    keys_deleted=deleted,
                    event_id=event.event_id,
                )
                await self._consumer.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "sync_event_consumer_error",
                    topic=self.TOPIC,
                    partition=msg.partition,
                    offset=msg.offset,
                )
