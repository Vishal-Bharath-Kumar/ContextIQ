# TASK-US028-04 — `EntityConsumer`: Kafka Consumer with Retry and Dead-Letter Queue

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US028-04 |
| User Story | US-028 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `EntityConsumer` — an `aiokafka` consumer that subscribes to `knowledge.chunk.indexed`, calls `EntityExtractor.extract()`, and writes results to `Neo4jEntityStore.merge_entities()`. On extraction failure, the chunk is re-queued to a retry topic up to `max_retries` times before being sent to a dead-letter topic and logged. Satisfies AC-1 (Kafka event trigger) and AC-6 (error logging + re-queue on failure).

## Implementation Details

**Technology:** Python 3.11+, `aiokafka>=2.0`, Pydantic v2, `pydantic-settings`, `asyncio`, `prometheus-client>=0.20`

**File locations:**
- `src/knowledge_graph/consumer.py` — `EntityConsumer`, `EntityConsumerSettings`
- `src/knowledge_graph/metrics.py` — Prometheus metrics for AC-5 SLA tracking
- `src/gateway/lifespan.py` — extend existing lifespan to start/stop the consumer

---

### Prometheus metrics

```python
# src/knowledge_graph/metrics.py
from prometheus_client import Histogram, Counter

entity_extraction_duration_ms = Histogram(
    "knowledge_graph_entity_extraction_duration_ms",
    "Wall-clock time for a single chunk entity extraction call",
    ["model_id"],
    buckets=[50, 100, 200, 300, 500, 750, 1000, 2000],
)

entity_extraction_total = Counter(
    "knowledge_graph_entity_extraction_total",
    "Total entity extraction attempts",
    ["status"],   # status: "success" | "retried" | "dead_lettered"
)

entities_extracted_total = Counter(
    "knowledge_graph_entities_extracted_total",
    "Total entities written to Neo4j",
    ["entity_type"],
)
```

---

### `EntityConsumerSettings`

```python
# src/knowledge_graph/consumer.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class EntityConsumerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENTITY_CONSUMER_", env_file=".env")

    kafka_bootstrap_servers: str = "localhost:9092"
    group_id:                str = "contextiq-entity-extraction"
    chunk_indexed_topic:     str = "knowledge.chunk.indexed"
    retry_topic:             str = "knowledge.chunk.indexed.retry"
    dead_letter_topic:       str = "knowledge.entity.extraction.dlq"
    # Number of re-queue attempts before sending to DLQ.
    max_retries:             int = 3
    enable_auto_commit:      bool = False
    max_poll_records:        int  = 50
```

---

### Retry envelope

Retried chunks carry an attempt counter so the consumer knows when to stop.

```python
# src/knowledge_graph/schemas/events.py  (extend existing file)
class ChunkRetryEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt:     int
    original:    ChunkIndexedEvent
```

---

### `EntityConsumer`

```python
# src/knowledge_graph/consumer.py (continued)
import asyncio
import json
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from src.knowledge_graph.extraction.extractor import EntityExtractor
from src.knowledge_graph.stores.neo4j_store   import Neo4jEntityStore
from src.knowledge_graph.schemas.events       import (
    ChunkIndexedEvent, ChunkRetryEnvelope, EntityExtractionFailedEvent,
)
from src.knowledge_graph.metrics import (
    entity_extraction_duration_ms, entity_extraction_total, entities_extracted_total,
)

logger = logging.getLogger(__name__)


class EntityConsumer:
    def __init__(
        self,
        extractor:   EntityExtractor,
        neo4j_store: Neo4jEntityStore,
        settings:    EntityConsumerSettings | None = None,
    ) -> None:
        self._extractor   = extractor
        self._neo4j_store = neo4j_store
        self._settings    = settings or EntityConsumerSettings()
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._running = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._settings.chunk_indexed_topic,
            self._settings.retry_topic,
            bootstrap_servers  = self._settings.kafka_bootstrap_servers,
            group_id           = self._settings.group_id,
            value_deserializer = lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit = self._settings.enable_auto_commit,
            max_poll_records   = self._settings.max_poll_records,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers  = self._settings.kafka_bootstrap_servers,
            value_serializer   = lambda v: json.dumps(v).encode("utf-8"),
        )
        await self._consumer.start()
        await self._producer.start()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def run(self) -> None:
        """Blocking consume loop. Run as asyncio.create_task from lifespan."""
        if self._consumer is None:
            raise RuntimeError("Call start() before run()")
        async for msg in self._consumer:
            if not self._running:
                break
            await self._handle_message(msg)
            await self._consumer.commit()

    async def _handle_message(self, msg) -> None:
        """
        Dispatch to the correct handler based on whether the message is
        a fresh ChunkIndexedEvent or a retried ChunkRetryEnvelope.
        """
        payload = msg.value
        if msg.topic == self._settings.retry_topic:
            envelope = ChunkRetryEnvelope.model_validate(payload)
            await self._process_chunk(envelope.original, attempt=envelope.attempt)
        else:
            event = ChunkIndexedEvent.model_validate(payload)
            await self._process_chunk(event, attempt=1)

    async def _process_chunk(self, event: ChunkIndexedEvent, attempt: int) -> None:
        try:
            result = await self._extractor.extract(event)

            entity_extraction_duration_ms.labels(
                model_id=self._extractor._settings.model_id
            ).observe(result.duration_ms)
            entity_extraction_total.labels(status="success").inc()

            await self._neo4j_store.merge_entities(result.entities)

            for entity in result.entities:
                entities_extracted_total.labels(entity_type=entity.entity_type.value).inc()

        except Exception as exc:
            logger.warning(
                "EntityConsumer: extraction failed chunk=%s attempt=%d error=%s",
                event.chunk_id, attempt, exc,
            )
            if attempt < self._settings.max_retries:
                entity_extraction_total.labels(status="retried").inc()
                await self._requeue(event, attempt + 1)
            else:
                entity_extraction_total.labels(status="dead_lettered").inc()
                await self._send_to_dlq(event, attempt, str(exc))

    async def _requeue(self, event: ChunkIndexedEvent, next_attempt: int) -> None:
        envelope = ChunkRetryEnvelope(attempt=next_attempt, original=event)
        await self._producer.send_and_wait(
            self._settings.retry_topic,
            value=envelope.model_dump(),
        )
        logger.info(
            "EntityConsumer: re-queued chunk=%s as attempt %d",
            event.chunk_id, next_attempt,
        )

    async def _send_to_dlq(
        self, event: ChunkIndexedEvent, attempt: int, error: str
    ) -> None:
        failed_event = EntityExtractionFailedEvent(
            chunk_id  = event.chunk_id,
            source_id = event.source_id,
            tenant_id = event.tenant_id,
            error     = error,
            failed_at = datetime.now(tz=timezone.utc),
            attempt   = attempt,
        )
        await self._producer.send_and_wait(
            self._settings.dead_letter_topic,
            value=failed_event.model_dump(),
        )
        logger.error(
            "EntityConsumer: chunk=%s exhausted %d retries; sent to DLQ. error=%s",
            event.chunk_id, attempt, error,
        )
```

**At-least-once + retry semantics:**

- `enable_auto_commit=False` — offset committed only after `_process_chunk` completes (success, re-queue, or DLQ)
- On `_requeue`: the original message offset is committed; the re-queued message on `retry_topic` becomes the new delivery unit
- On DLQ: the original message offset is committed; the chunk will not be retried again unless an operator re-publishes from the DLQ
- On process crash mid-`_process_chunk`: the message is redelivered; because `Neo4jEntityStore.merge_entities()` uses `MERGE`, a partial write is safe to replay

**Lifespan integration:**

```python
# src/gateway/lifespan.py — extend startup block
entity_consumer = EntityConsumer(
    extractor   = EntityExtractor(),
    neo4j_store = app.state.neo4j_store,
)
entity_consumer_task = asyncio.create_task(
    _start_and_run(entity_consumer),
    name="entity_consumer",
)
app.state.entity_consumer = entity_consumer

# Shutdown
await app.state.entity_consumer.stop()
entity_consumer_task.cancel()
```

## Acceptance Criteria

- [ ] `EntityConsumer` subscribes to both `knowledge.chunk.indexed` and `knowledge.chunk.indexed.retry`
- [ ] Successful extraction writes entities to Neo4j and increments `entity_extraction_total{status="success"}`
- [ ] On first failure, chunk is re-queued to retry topic with `attempt=2`; `entity_extraction_total{status="retried"}` incremented
- [ ] After `max_retries` failures, chunk sent to DLQ topic; `entity_extraction_total{status="dead_lettered"}` incremented; no further retries
- [ ] A message on the retry topic with `attempt` payload routes through `_process_chunk(event, attempt=N)`
- [ ] `entity_extraction_duration_ms` histogram is observed for every successful extraction
- [ ] Kafka offset is committed after every message — regardless of success, re-queue, or DLQ outcome

## Dependencies

- TASK-US028-01 (`ChunkIndexedEvent`, `ChunkRetryEnvelope`, `EntityExtractionFailedEvent`)
- TASK-US028-02 (`EntityExtractor`)
- TASK-US028-03 (`Neo4jEntityStore`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `AIOKafkaConsumer`, `AIOKafkaProducer`, `EntityExtractor`, and `Neo4jEntityStore` via `AsyncMock`; no live Kafka or Neo4j in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
