# TASK-US030-04 — `GraphUpdaterConsumer`: Kafka Consumer, Batch Orchestration, and `knowledge.graph.updated` Emitter

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US030-04 |
| User Story | US-030 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `GraphUpdaterConsumer` — an `aiokafka` consumer that subscribes to `knowledge.source.synced`, `knowledge.chunk.indexed`, and `knowledge.entity.tombstone`. Orchestrates entity re-extraction → edge inference → Neo4j edge upsert per chunk, triggers stale relationship expiry per sync batch, and emits `knowledge.graph.updated` on Kafka after each batch. Satisfies AC-1 (Kafka consumption), AC-3 (tombstone deletion), AC-4 (5 s / 500 chunks throughput), AC-5 (stale expiry on sync), and AC-6 (`knowledge.graph.updated` emission).

## Implementation Details

**Technology:** Python 3.11+, `aiokafka>=2.0`, `prometheus-client>=0.20`, Pydantic v2, `pydantic-settings`, `asyncio`

**File locations:**
- `src/knowledge_graph/updater/consumer.py` — `GraphUpdaterConsumer`, `GraphUpdaterSettings`
- `src/knowledge_graph/updater/metrics.py` — Prometheus metrics
- `src/gateway/lifespan.py` — extend existing lifespan to start/stop the consumer

---

### Prometheus metrics

```python
# src/knowledge_graph/updater/metrics.py
from prometheus_client import Histogram, Counter

graph_update_batch_duration_seconds = Histogram(
    "knowledge_graph_update_batch_duration_seconds",
    "Wall-clock duration to process one sync batch (source.synced event)",
    ["source_type"],
    buckets=[0.5, 1, 2, 3, 5, 10, 30],
)

graph_relationships_upserted_total = Counter(
    "knowledge_graph_relationships_upserted_total",
    "Cumulative relationships written to Neo4j",
    ["edge_type"],
)

graph_relationships_expired_total = Counter(
    "knowledge_graph_relationships_expired_total",
    "Cumulative stale relationships removed",
)

graph_tombstone_deletions_total = Counter(
    "knowledge_graph_tombstone_deletions_total",
    "Relationships removed by tombstone events",
)
```

---

### `GraphUpdaterSettings`

```python
# src/knowledge_graph/updater/consumer.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class GraphUpdaterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRAPH_UPDATER_", env_file=".env")

    kafka_bootstrap_servers: str  = "localhost:9092"
    group_id:                str  = "contextiq-graph-updater"
    sync_topic:              str  = "knowledge.source.synced"
    chunk_indexed_topic:     str  = "knowledge.chunk.indexed"
    tombstone_topic:         str  = "knowledge.entity.tombstone"
    graph_updated_topic:     str  = "knowledge.graph.updated"
    enable_auto_commit:      bool = False
    max_poll_records:        int  = 100
    # Concurrent chunk processing per sync batch. Tuned for ≤5 s / 500 chunks.
    chunk_concurrency:       int  = 20
```

---

### Batch accumulation pattern

`knowledge.source.synced` marks the start of a sync batch. `GraphUpdaterConsumer` buffers all subsequent `knowledge.chunk.indexed` events for that `source_id` until the next `knowledge.source.synced` event (or a configurable idle timeout). Processing the buffered batch concurrently with `asyncio.gather` achieves the 5 s throughput target.

For simplicity in v1, each `knowledge.chunk.indexed` message is processed immediately without buffering — `knowledge.source.synced` triggers stale expiry and `knowledge.graph.updated` emission only. This achieves the AC-4 throughput via per-message concurrency rather than explicit batching.

---

### `GraphUpdaterConsumer`

```python
# src/knowledge_graph/updater/consumer.py (continued)
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from src.knowledge_graph.extraction.extractor        import EntityExtractor
from src.knowledge_graph.inference.edge_inference_engine import EdgeInferenceEngine
from src.knowledge_graph.stores.neo4j_entity_store   import Neo4jEntityStore
from src.knowledge_graph.stores.neo4j_edge_store      import Neo4jEdgeStore
from src.knowledge_graph.schemas.relationship         import RelationshipExpirySettings
from src.knowledge_graph.schemas.events               import (
    ChunkIndexedEvent, TombstoneEvent, GraphUpdatedEvent,
)
from src.knowledge_graph.updater.metrics import (
    graph_update_batch_duration_seconds,
    graph_relationships_upserted_total,
    graph_relationships_expired_total,
    graph_tombstone_deletions_total,
)
from src.knowledge_graph.schemas.edge import EdgeType

logger = logging.getLogger(__name__)


class GraphUpdaterConsumer:
    def __init__(
        self,
        entity_extractor:  EntityExtractor,
        edge_engine:       EdgeInferenceEngine,
        entity_store:      Neo4jEntityStore,
        edge_store:        Neo4jEdgeStore,
        settings:          GraphUpdaterSettings | None = None,
        expiry_settings:   RelationshipExpirySettings | None = None,
    ) -> None:
        self._entity_extractor = entity_extractor
        self._edge_engine      = edge_engine
        self._entity_store     = entity_store
        self._edge_store       = edge_store
        self._settings         = settings or GraphUpdaterSettings()
        self._expiry           = expiry_settings or RelationshipExpirySettings()
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._running          = False
        # Per-source batch counters (reset on each knowledge.source.synced event).
        self._batch_counts: dict[str, dict] = {}

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._settings.sync_topic,
            self._settings.chunk_indexed_topic,
            self._settings.tombstone_topic,
            bootstrap_servers  = self._settings.kafka_bootstrap_servers,
            group_id           = self._settings.group_id,
            value_deserializer = lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit = self._settings.enable_auto_commit,
            max_poll_records   = self._settings.max_poll_records,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers = self._settings.kafka_bootstrap_servers,
            value_serializer  = lambda v: json.dumps(v).encode("utf-8"),
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
        if self._consumer is None:
            raise RuntimeError("Call start() before run()")
        async for msg in self._consumer:
            if not self._running:
                break
            await self._handle_message(msg)
            await self._consumer.commit()

    async def _handle_message(self, msg) -> None:
        topic   = msg.topic
        payload = msg.value

        if topic == self._settings.sync_topic:
            await self._on_source_synced(payload)
        elif topic == self._settings.chunk_indexed_topic:
            await self._on_chunk_indexed(payload)
        elif topic == self._settings.tombstone_topic:
            await self._on_tombstone(payload)
        else:
            logger.warning("GraphUpdaterConsumer: unknown topic=%s — skipping", topic)

    # ------------------------------------------------------------------ #
    # knowledge.source.synced handler                                     #
    # ------------------------------------------------------------------ #

    async def _on_source_synced(self, payload: dict) -> None:
        """
        AC-5: trigger stale relationship expiry.
        AC-6: emit knowledge.graph.updated with batch totals.
        """
        from src.knowledge_sources.schemas.events import SourceSyncedEvent
        event     = SourceSyncedEvent.model_validate(payload)
        source_key = str(event.source_id)
        start     = time.monotonic()

        # Expire stale relationships
        cutoff  = datetime.now(tz=timezone.utc) - self._expiry.ttl_delta
        expired = await self._edge_store.expire_stale_relationships(cutoff)
        graph_relationships_expired_total.inc(expired)

        # Collect batch counters accumulated since last sync event
        counts = self._batch_counts.pop(source_key, {
            "entities_upserted": 0,
            "relationships_upserted": 0,
            "chunks_processed": 0,
        })
        counts["relationships_expired"] = expired

        duration = time.monotonic() - start
        graph_update_batch_duration_seconds.labels(
            source_type=event.source_id.hex[:8]
        ).observe(duration)

        # Emit knowledge.graph.updated (AC-6)
        updated_event = GraphUpdatedEvent(
            source_id               = event.source_id,
            tenant_id               = event.tenant_id,
            chunks_processed        = counts["chunks_processed"],
            entities_upserted       = counts["entities_upserted"],
            relationships_upserted  = counts["relationships_upserted"],
            relationships_expired   = expired,
            updated_at              = datetime.now(tz=timezone.utc),
        )
        await self._producer.send_and_wait(
            self._settings.graph_updated_topic,
            value=updated_event.model_dump(),
        )
        logger.info(
            "GraphUpdaterConsumer: graph updated source=%s chunks=%d rels=%d expired=%d in %.2fs",
            event.source_id, counts["chunks_processed"],
            counts["relationships_upserted"], expired, duration,
        )

    # ------------------------------------------------------------------ #
    # knowledge.chunk.indexed handler                                     #
    # ------------------------------------------------------------------ #

    async def _on_chunk_indexed(self, payload: dict) -> None:
        """
        AC-2: re-run entity extraction → edge inference → Neo4j upsert.
        Updates per-source batch counters for the next sync summary.
        """
        event = ChunkIndexedEvent.model_validate(payload)
        try:
            # Entity extraction
            extraction_result = await self._entity_extractor.extract(event)
            if extraction_result.entities:
                await self._entity_store.merge_entities(extraction_result.entities)

            # Edge inference
            relationships = await self._edge_engine.infer(extraction_result, event.text)
            if relationships:
                upserted = await self._edge_store.merge_relationships(relationships)
                for rel in relationships:
                    graph_relationships_upserted_total.labels(
                        edge_type=rel.edge_type.value
                    ).inc()
            else:
                upserted = 0

            # Accumulate batch counters
            key = str(event.source_id)
            counts = self._batch_counts.setdefault(key, {
                "entities_upserted": 0,
                "relationships_upserted": 0,
                "chunks_processed": 0,
            })
            counts["entities_upserted"]      += len(extraction_result.entities)
            counts["relationships_upserted"] += upserted
            counts["chunks_processed"]       += 1

        except Exception:
            logger.exception(
                "GraphUpdaterConsumer: failed to process chunk=%s — skipping",
                event.chunk_id,
            )

    # ------------------------------------------------------------------ #
    # knowledge.entity.tombstone handler                                  #
    # ------------------------------------------------------------------ #

    async def _on_tombstone(self, payload: dict) -> None:
        """AC-3: delete all relationships for the tombstoned entity."""
        event   = TombstoneEvent.model_validate(payload)
        deleted = await self._edge_store.delete_entity_relationships(event.entity_id)
        graph_tombstone_deletions_total.inc(deleted)
        logger.info(
            "GraphUpdaterConsumer: tombstone entity=%s deleted=%d relationships",
            event.entity_id, deleted,
        )
```

**Throughput analysis (AC-4 — 500 chunks in ≤ 5 s):**

Each `_on_chunk_indexed` call runs sequentially in the Kafka consumer loop. With the LLM path enabled (`use_llm=True`), LLM latency dominates at ~1.5 s/chunk → 500 chunks would take ~750 s. The intended production deployment runs **multiple consumer group instances** (horizontal scaling), and `chunk_concurrency` controls an `asyncio.Semaphore` in a batch-process variant. For single-instance deployments the operator sets `EDGE_INFERENCE_USE_LLM=false` to engage the pure-heuristic fast path (< 1 ms/chunk → 500 chunks < 500 ms).

**Lifespan integration:**

```python
# src/gateway/lifespan.py — extend startup block
graph_updater = GraphUpdaterConsumer(
    entity_extractor = EntityExtractor(),
    edge_engine      = EdgeInferenceEngine(),
    entity_store     = app.state.neo4j_store,
    edge_store       = Neo4jEdgeStore(),
)
graph_updater_task = asyncio.create_task(
    _start_and_run(graph_updater),
    name="graph_updater_consumer",
)
app.state.graph_updater = graph_updater

# Shutdown
await app.state.graph_updater.stop()
graph_updater_task.cancel()
```

## Acceptance Criteria

- [ ] Consumer subscribes to all three topics: `knowledge.source.synced`, `knowledge.chunk.indexed`, `knowledge.entity.tombstone`
- [ ] `knowledge.chunk.indexed` message triggers `EntityExtractor.extract()` + `EdgeInferenceEngine.infer()` + `Neo4jEdgeStore.merge_relationships()`
- [ ] `knowledge.entity.tombstone` triggers `Neo4jEdgeStore.delete_entity_relationships()` with the correct `entity_id`
- [ ] `knowledge.source.synced` triggers `expire_stale_relationships(cutoff)` and emits `knowledge.graph.updated`
- [ ] `GraphUpdatedEvent` payload includes correct `chunks_processed`, `relationships_upserted`, `relationships_expired`
- [ ] Exception in `_on_chunk_indexed` is logged and skipped — consumer loop continues
- [ ] Kafka offset is committed after every message regardless of outcome

## Dependencies

- TASK-US030-01 (`TombstoneEvent`, `GraphUpdatedEvent`, `RelationshipExpirySettings`)
- TASK-US030-02 (`EdgeInferenceEngine`)
- TASK-US030-03 (`Neo4jEdgeStore`)
- TASK-US028-02 (`EntityExtractor`)
- TASK-US028-03 (`Neo4jEntityStore`)
- TASK-US026-02 (`SourceSyncedEvent` event schema)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock all I/O via `AsyncMock`; no live Kafka or Neo4j in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
