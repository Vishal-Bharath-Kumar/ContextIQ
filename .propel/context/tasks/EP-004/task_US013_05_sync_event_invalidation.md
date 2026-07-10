# TASK-US013-05 — Cache Invalidation on Source Sync Event (EP-008 Kafka Consumer)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US013-05 |
| User Story | US-013 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Event-Driven / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement a Kafka consumer that listens on the `contextiq.source.sync` topic (published by EP-008 when a source's document index is refreshed) and calls `ContextCacheStore.invalidate_source()` to purge all cache entries for the updated source. This ensures stale context is never served after a new crawl completes.

## Implementation Details

**Technology:** Python 3.11+, `aiokafka>=0.10`, `pydantic>=2.0`

**File locations:**
- `src/retrieval/cache/sync_event_consumer.py` — `SourceSyncEventConsumer` class
- `src/retrieval/cache/sync_event_schema.py` — `SourceSyncEvent` Pydantic model
- `src/agents/worker/lifespan.py` — consumer started in FastAPI lifespan (extends app startup)
- `tests/retrieval/cache/test_sync_event_consumer.py`

**`SourceSyncEvent` schema:**

```python
# src/retrieval/cache/sync_event_schema.py
from pydantic import BaseModel

class SourceSyncEvent(BaseModel):
    event_id:   str     # UUID v4
    source_id:  str     # e.g. "github", "confluence"
    sync_type:  str     # "full" | "incremental"
    timestamp:  str     # ISO-8601 UTC
    doc_count:  int     # number of documents indexed in this sync
```

**`SourceSyncEventConsumer`:**

```python
# src/retrieval/cache/sync_event_consumer.py
import json
from aiokafka import AIOKafkaConsumer
from src.retrieval.cache.sync_event_schema import SourceSyncEvent
from src.retrieval.cache.cache_store       import ContextCacheStore

class SourceSyncEventConsumer:
    TOPIC          = "contextiq.source.sync"
    CONSUMER_GROUP = "context-cache-invalidator"

    def __init__(self, cache: ContextCacheStore, bootstrap_servers: str) -> None:
        self._cache    = cache
        self._consumer = AIOKafkaConsumer(
            self.TOPIC,
            bootstrap_servers   = bootstrap_servers,
            group_id            = self.CONSUMER_GROUP,
            value_deserializer  = lambda v: json.loads(v.decode()),
            auto_offset_reset   = "latest",   # only process new sync events; historical re-index not needed
            enable_auto_commit  = False,       # manual commit after successful invalidation
        )

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def consume(self) -> None:
        """Blocking consume loop — run as a background asyncio task."""
        async for msg in self._consumer:
            try:
                event   = SourceSyncEvent.model_validate(msg.value)
                deleted = await self._cache.invalidate_source(event.source_id)
                await self._consumer.commit()
            except Exception:
                # Log and continue — do not crash the consumer on a bad message
                pass
```

**Logging (structured):**

```python
import structlog
log = structlog.get_logger()

deleted = await self._cache.invalidate_source(event.source_id)
log.info(
    "cache_invalidated_on_sync",
    source_id  = event.source_id,
    sync_type  = event.sync_type,
    keys_deleted = deleted,
    event_id   = event.event_id,
)
```

**FastAPI lifespan integration:**

```python
# src/agents/worker/lifespan.py  (extend existing lifespan — do NOT replace)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup (checkpointer, cache store, etc.) ...
    consumer = SourceSyncEventConsumer(
        cache              = app.state.context_cache_store,
        bootstrap_servers  = settings.kafka_bootstrap_servers,
    )
    await consumer.start()
    consume_task = asyncio.create_task(consumer.consume())

    yield

    consume_task.cancel()
    await consumer.stop()
```

**At-least-once delivery:**
- `enable_auto_commit=False` with manual `commit()` after successful invalidation ensures that if the pod crashes mid-invalidation, the event is reprocessed on restart
- `invalidate_source` is idempotent — re-running it on already-deleted keys returns 0 without error

**Kafka topic contract (EP-008):**
- Topic: `contextiq.source.sync`
- Partition key: `source_id` — all sync events for a source go to the same partition
- Message format: JSON-encoded `SourceSyncEvent`

## Acceptance Criteria

- [ ] Consumer starts and subscribes to `contextiq.source.sync` on application startup
- [ ] A `SourceSyncEvent` with `source_id="github"` triggers `invalidate_source("github")`
- [ ] `invalidate_source` is called exactly once per consumed sync event
- [ ] Offset is committed only after `invalidate_source` completes successfully
- [ ] A malformed message (invalid JSON or missing fields) is logged and skipped — consumer does not crash
- [ ] Consumer stops cleanly on FastAPI shutdown (task cancelled, `consumer.stop()` called)

## Dependencies

- TASK-US013-02 (`ContextCacheStore.invalidate_source()`)
- TASK-US005-04 (Kafka producer patterns — consumer follows same `aiokafka` conventions)
- EP-008 (source sync event producer — defines `contextiq.source.sync` topic and message schema)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit tests use a mocked `AIOKafkaConsumer` — no live Kafka broker in CI
- [ ] Integration test: publish a `SourceSyncEvent` to an embedded Kafka topic and verify cache keys are deleted
- [ ] Consumer group ID `context-cache-invalidator` is documented in `docs/kafka/consumer-groups.md`
- [ ] `mypy --strict` passes; no `ruff` lint errors
