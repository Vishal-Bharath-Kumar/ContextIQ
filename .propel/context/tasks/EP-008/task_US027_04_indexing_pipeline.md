# TASK-US027-04 — Kafka Consumer and Indexing Pipeline Orchestrator

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US027-04 |
| User Story | US-027 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `IndexingConsumer` — an `aiokafka` consumer that listens on `knowledge.source.synced` (and `knowledge.document.deleted`), orchestrates the embed → Qdrant upsert → OpenSearch bulk index → PostgreSQL upsert pipeline per event, and satisfies AC-1 (Kafka consumption), AC-5 (PostgreSQL update), AC-6 (≥ 1,000 chunks/min throughput), and AC-7 (deletion event routing).

## Implementation Details

**Technology:** Python 3.11+, `aiokafka>=2.0`, Pydantic v2, `pydantic-settings`, `asyncio`

**File locations:**
- `src/indexing/consumer.py` — `IndexingConsumer`, `IndexingConsumerSettings`
- `src/indexing/pipeline.py` — `IndexingPipeline` (pure orchestration, no I/O itself)
- `src/gateway/lifespan.py` — extend existing lifespan to start/stop the consumer

---

### `IndexingConsumerSettings`

```python
# src/indexing/consumer.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class IndexingConsumerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INDEXING_CONSUMER_", env_file=".env")

    kafka_bootstrap_servers: str  = "localhost:9092"
    group_id:                str  = "contextiq-indexing"
    sync_topic:              str  = "knowledge.source.synced"
    deletion_topic:          str  = "knowledge.document.deleted"
    # Max Kafka messages fetched per poll iteration.
    max_poll_records:        int  = 100
    # Seconds to wait for new messages before iterating again.
    poll_timeout_ms:         int  = 1000
    # At-least-once: commit after successful processing.
    enable_auto_commit:      bool = False
```

---

### `knowledge.source.synced` event payload

The event is emitted by `SyncJobExecutor` (TASK-US026-02). The indexing consumer parses this JSON:

```python
# src/indexing/schemas/events.py
from pydantic import BaseModel, ConfigDict
from uuid     import UUID
from datetime import datetime

class SourceSyncedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_type:      str       # "knowledge_source_synced"
    source_id:       UUID
    tenant_id:       str
    job_id:          UUID
    items_processed: int
    synced_at:       datetime

class DocumentDeletedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_type:   str     # "knowledge_document_deleted"
    source_id:    UUID
    tenant_id:    str
    document_id:  str
```

---

### `IndexingPipeline` (pure orchestration)

`IndexingPipeline` is separate from the Kafka consumer so it can be exercised in tests without a running broker.

```python
# src/indexing/pipeline.py
import asyncio
from datetime import datetime, timezone
from uuid     import UUID

from src.indexing.embedding.service           import EmbeddingService
from src.indexing.stores.qdrant_indexer       import QdrantIndexer
from src.indexing.stores.opensearch_indexer   import OpenSearchIndexer
from src.indexing.repositories.chunk_repository import ChunkRepository
from src.indexing.schemas.chunk               import ChunkPayload, ChunkMetadata
from src.connector_sdk.registry              import ConnectorRegistry

class IndexingPipeline:
    def __init__(
        self,
        embedder:   EmbeddingService,
        qdrant:     QdrantIndexer,
        opensearch: OpenSearchIndexer,
        chunk_repo: ChunkRepository,
        registry:   ConnectorRegistry,
    ) -> None:
        self._embedder   = embedder
        self._qdrant     = qdrant
        self._opensearch = opensearch
        self._chunk_repo = chunk_repo
        self._registry   = registry

    async def run_for_source(self, source_id: UUID, tenant_id: str) -> int:
        """
        1. Fetch chunks from the connector (via registry).
        2. Ensure Qdrant collection and OpenSearch index exist.
        3. Embed all chunks in parallel batches.
        4. Upsert vectors into Qdrant.
        5. Bulk index text into OpenSearch.
        6. Upsert chunk metadata into PostgreSQL.
        Returns number of chunks indexed.
        """
        connector = self._registry.get(source_id)
        chunks: list[ChunkPayload] = await connector.get_chunks()

        await asyncio.gather(
            self._qdrant.ensure_collection(source_id, tenant_id),
            self._opensearch.ensure_index(tenant_id),
        )

        indexed_chunks = await self._embedder.embed_batch(chunks)

        await asyncio.gather(
            self._qdrant.upsert(indexed_chunks, source_id, tenant_id),
            self._opensearch.bulk_index(indexed_chunks, tenant_id),
        )

        now = datetime.now(tz=timezone.utc)
        metadata = [
            ChunkMetadata(
                chunk_id        = c.payload.chunk_id,
                source_id       = c.payload.source_id,
                tenant_id       = c.payload.tenant_id,
                document_id     = c.payload.document_id,
                embedding_model = c.model_id,
                token_count     = c.payload.token_count,
                indexed_at      = now,
            )
            for c in indexed_chunks
        ]
        await self._chunk_repo.upsert_batch(metadata)
        return len(indexed_chunks)
```

---

### `IndexingConsumer`

```python
# src/indexing/consumer.py (continued)
import json, logging
from aiokafka import AIOKafkaConsumer

from src.indexing.schemas.events     import SourceSyncedEvent, DocumentDeletedEvent
from src.indexing.pipeline           import IndexingPipeline
from src.indexing.stores.deletion_handler import DeletionHandler

logger = logging.getLogger(__name__)

class IndexingConsumer:
    def __init__(
        self,
        pipeline:          IndexingPipeline,
        deletion_handler:  DeletionHandler,
        settings:          IndexingConsumerSettings | None = None,
    ) -> None:
        self._pipeline          = pipeline
        self._deletion_handler  = deletion_handler
        self._settings          = settings or IndexingConsumerSettings()
        self._consumer: AIOKafkaConsumer | None = None
        self._running: bool = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._settings.sync_topic,
            self._settings.deletion_topic,
            bootstrap_servers  = self._settings.kafka_bootstrap_servers,
            group_id           = self._settings.group_id,
            value_deserializer = lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit = self._settings.enable_auto_commit,
            max_poll_records   = self._settings.max_poll_records,
        )
        await self._consumer.start()
        self._running = True
        logger.info("IndexingConsumer started on topics: %s, %s",
                    self._settings.sync_topic, self._settings.deletion_topic)

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()

    async def run(self) -> None:
        """Blocking consume loop. Run as an asyncio task from lifespan."""
        if self._consumer is None:
            raise RuntimeError("Call start() before run()")
        async for msg in self._consumer:
            if not self._running:
                break
            await self._handle_message(msg)
            await self._consumer.commit()

    async def _handle_message(self, msg) -> None:
        payload    = msg.value
        event_type = payload.get("event_type", "")

        try:
            if event_type == "knowledge_source_synced":
                event = SourceSyncedEvent.model_validate(payload)
                count = await self._pipeline.run_for_source(
                    source_id = event.source_id,
                    tenant_id = event.tenant_id,
                )
                logger.info(
                    "Indexed %d chunks for source=%s job=%s",
                    count, event.source_id, event.job_id,
                )
            elif event_type == "knowledge_document_deleted":
                event = DocumentDeletedEvent.model_validate(payload)
                await self._deletion_handler.handle(
                    document_id = event.document_id,
                    source_id   = event.source_id,
                    tenant_id   = event.tenant_id,
                )
                logger.info(
                    "Deleted stale embeddings for document=%s source=%s",
                    event.document_id, event.source_id,
                )
            else:
                logger.warning("IndexingConsumer: unknown event_type=%s — skipping", event_type)
        except Exception:
            # Log and skip the message rather than crashing the consumer loop.
            # The commit below will advance the offset; this is intentional:
            # poison-pill messages must not halt the pipeline for all sources.
            logger.exception("IndexingConsumer: failed to process message; skipping")
```

**At-least-once semantics:** `enable_auto_commit=False` + explicit `await consumer.commit()` after successful `_handle_message`. If the process crashes mid-pipeline, the message is redelivered. `ChunkRepository.upsert_batch` and `QdrantIndexer.upsert` are both idempotent, so redelivery is safe.

---

### Lifespan integration

```python
# src/gateway/lifespan.py  — extend existing lifespan context manager
from contextlib import asynccontextmanager
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # … existing startup (model registry, connector registry, scheduler) …

    # Start indexing consumer
    consumer: IndexingConsumer = _build_indexing_consumer(app)
    consumer_task = asyncio.create_task(
        _start_and_run_consumer(consumer),
        name="indexing_consumer",
    )
    app.state.indexing_consumer = consumer

    yield

    # Shutdown
    await consumer.stop()
    consumer_task.cancel()
    # … existing teardown …

async def _start_and_run_consumer(consumer: IndexingConsumer) -> None:
    await consumer.start()
    await consumer.run()
```

## Acceptance Criteria

- [ ] `IndexingConsumer` subscribes to both `knowledge.source.synced` and `knowledge.document.deleted` topics
- [ ] A `knowledge_source_synced` message triggers `IndexingPipeline.run_for_source()` with correct `source_id` and `tenant_id`
- [ ] A `knowledge_document_deleted` message triggers `DeletionHandler.handle()` with correct fields
- [ ] Messages with unknown `event_type` are logged and skipped without crashing the consumer loop
- [ ] Kafka offsets are committed only after successful message processing (at-least-once)
- [ ] `IndexingPipeline.run_for_source()` calls `ensure_collection` and `ensure_index` concurrently (single `asyncio.gather`)
- [ ] `IndexingPipeline.run_for_source()` calls `qdrant.upsert` and `opensearch.bulk_index` concurrently (single `asyncio.gather`)

## Dependencies

- TASK-US027-01 (`ChunkMetadata`, `ChunkRepository`)
- TASK-US027-02 (`EmbeddingService`)
- TASK-US027-03 (`QdrantIndexer`, `OpenSearchIndexer`, `DeletionHandler`)
- TASK-US026-02 (`SyncJobExecutor` emits `knowledge.source.synced`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `IndexingConsumer` tests use a mocked `AIOKafkaConsumer`; no live Kafka in CI
- [ ] `IndexingPipeline` tests use `AsyncMock` for all store dependencies
- [ ] `mypy --strict` passes; no `ruff` lint errors
