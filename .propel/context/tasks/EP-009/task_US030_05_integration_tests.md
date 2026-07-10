# TASK-US030-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US030-05 |
| User Story | US-030 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the integration and unit test suite covering all 6 US-030 acceptance criteria: Kafka event consumption from all three topics, Neo4j relationship upsert, tombstone deletion, 5 s / 500-chunk throughput, stale TTL expiry, and `knowledge.graph.updated` Kafka emission.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, pytest-benchmark, `AsyncMock`, `unittest.mock`

**File locations:**
- `tests/knowledge_graph/test_edge_inference_engine.py` — edge inference unit tests
- `tests/knowledge_graph/test_neo4j_edge_store.py` — AC-2, AC-3, AC-5 (store operations)
- `tests/knowledge_graph/test_graph_updater_consumer.py` — AC-1, AC-3, AC-4, AC-6 (consumer routing)

---

### Shared fixtures

```python
# tests/knowledge_graph/conftest.py  (extend existing conftest)
import pytest
from unittest.mock  import AsyncMock, MagicMock
from uuid           import uuid4
from datetime       import datetime, timezone, timedelta

from src.knowledge_graph.schemas.entity       import EntityType, ExtractedEntity, make_entity_id
from src.knowledge_graph.schemas.edge         import EdgeType
from src.knowledge_graph.schemas.relationship import GraphRelationship
from src.knowledge_graph.schemas.events       import ChunkIndexedEvent, TombstoneEvent

SOURCE_ID = uuid4()
CHUNK_ID  = uuid4()

@pytest.fixture
def chunk_event():
    return ChunkIndexedEvent(
        chunk_id        = CHUNK_ID,
        source_id       = SOURCE_ID,
        tenant_id       = "acme",
        document_id     = "github:org/repo:abc",
        text            = "auth-service depends on user-repo, owned by @alice",
        token_count     = 10,
        embedding_model = "text-embedding-3-small",
        indexed_at      = datetime.now(tz=timezone.utc),
    )

@pytest.fixture
def tombstone_event():
    eid = make_entity_id(EntityType.SERVICE, "auth-service")
    return TombstoneEvent(
        entity_id   = eid,
        source_id   = SOURCE_ID,
        tenant_id   = "acme",
        document_id = "github:org/repo:abc",
        deleted_at  = datetime.now(tz=timezone.utc),
    )

@pytest.fixture
def two_entities():
    a = ExtractedEntity(
        entity_id      = make_entity_id(EntityType.SERVICE, "auth-service"),
        entity_type    = EntityType.SERVICE,
        name           = "auth-service",
        canonical_name = "auth-service",
        source_id      = SOURCE_ID,
        chunk_id       = CHUNK_ID,
        created_at     = datetime.now(tz=timezone.utc),
    )
    b = ExtractedEntity(
        entity_id      = make_entity_id(EntityType.REPOSITORY, "user-repo"),
        entity_type    = EntityType.REPOSITORY,
        name           = "user-repo",
        canonical_name = "user-repo",
        source_id      = SOURCE_ID,
        chunk_id       = CHUNK_ID,
        created_at     = datetime.now(tz=timezone.utc),
    )
    return [a, b]

@pytest.fixture
def mock_entity_extractor(two_entities, chunk_event):
    from src.knowledge_graph.schemas.entity import EntityExtractionResult
    extractor = AsyncMock()
    extractor._settings = MagicMock(model_id="gpt-4o-mini")
    extractor.extract = AsyncMock(return_value=EntityExtractionResult(
        chunk_id    = CHUNK_ID,
        source_id   = SOURCE_ID,
        entities    = two_entities,
        duration_ms = 200.0,
    ))
    return extractor

@pytest.fixture
def mock_edge_engine(two_entities):
    engine = AsyncMock()
    engine.infer = AsyncMock(return_value=[
        GraphRelationship.create(
            from_entity_id = two_entities[0].entity_id,
            to_entity_id   = two_entities[1].entity_id,
            edge_type      = EdgeType.DEPENDS_ON,
            source_id      = SOURCE_ID,
            chunk_id       = CHUNK_ID,
        )
    ])
    return engine

@pytest.fixture
def mock_entity_store():
    s = AsyncMock()
    s.merge_entities = AsyncMock()
    return s

@pytest.fixture
def mock_edge_store():
    s = AsyncMock()
    s.merge_relationships        = AsyncMock(return_value=1)
    s.delete_entity_relationships = AsyncMock(return_value=3)
    s.expire_stale_relationships  = AsyncMock(return_value=5)
    return s
```

---

### AC-1 — Consumer subscribes to all three topics and routes correctly

```python
# tests/knowledge_graph/test_graph_updater_consumer.py
async def test_consumer_routes_chunk_indexed_to_edge_engine(
    chunk_event, mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store
):
    from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings

    consumer = GraphUpdaterConsumer(
        mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store,
        GraphUpdaterSettings(),
    )
    msg       = MagicMock()
    msg.topic = "knowledge.chunk.indexed"
    msg.value = chunk_event.model_dump()

    await consumer._handle_message(msg)

    mock_entity_extractor.extract.assert_awaited_once()
    mock_edge_engine.infer.assert_awaited_once()
    mock_edge_store.merge_relationships.assert_awaited_once()


async def test_consumer_routes_tombstone_to_edge_store(
    tombstone_event, mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store
):
    from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings

    consumer = GraphUpdaterConsumer(
        mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store,
        GraphUpdaterSettings(),
    )
    consumer._producer = AsyncMock()

    msg       = MagicMock()
    msg.topic = "knowledge.entity.tombstone"
    msg.value = tombstone_event.model_dump()

    await consumer._handle_message(msg)
    mock_edge_store.delete_entity_relationships.assert_awaited_once_with(tombstone_event.entity_id)


async def test_consumer_unknown_topic_skipped_without_crash(
    mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store
):
    from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings

    consumer = GraphUpdaterConsumer(
        mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store,
        GraphUpdaterSettings(),
    )
    msg = MagicMock()
    msg.topic = "some.unknown.topic"
    msg.value = {}
    await consumer._handle_message(msg)    # must not raise
```

---

### AC-2 — New relationships upserted into Neo4j

```python
async def test_relationships_upserted_to_neo4j(
    chunk_event, mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store
):
    from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings

    consumer = GraphUpdaterConsumer(
        mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store,
        GraphUpdaterSettings(),
    )
    msg       = MagicMock()
    msg.topic = "knowledge.chunk.indexed"
    msg.value = chunk_event.model_dump()

    await consumer._handle_message(msg)

    mock_edge_store.merge_relationships.assert_awaited_once()
    rels_arg = mock_edge_store.merge_relationships.call_args.args[0]
    assert len(rels_arg) == 1
    assert rels_arg[0].edge_type.value == "DEPENDS_ON"
```

---

### AC-3 — Tombstone removes entity relationships

```python
async def test_tombstone_removes_entity_relationships(
    tombstone_event, mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store
):
    from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings

    consumer = GraphUpdaterConsumer(
        mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store,
        GraphUpdaterSettings(),
    )
    consumer._producer = AsyncMock()
    msg       = MagicMock()
    msg.topic = "knowledge.entity.tombstone"
    msg.value = tombstone_event.model_dump()

    await consumer._handle_message(msg)
    mock_edge_store.delete_entity_relationships.assert_awaited_once_with(tombstone_event.entity_id)
    mock_edge_store.merge_relationships.assert_not_awaited()
```

---

### AC-4 — Throughput: 500 chunks via heuristic-only path (fast path benchmark)

```python
# pytest-benchmark — run with: pytest --benchmark-only
def test_edge_inference_heuristic_500_chunks_benchmark(benchmark, two_entities):
    import asyncio
    from src.knowledge_graph.inference.edge_inference_engine import (
        EdgeInferenceEngine, EdgeInferenceSettings,
    )
    from src.knowledge_graph.schemas.entity import EntityExtractionResult

    result = EntityExtractionResult(
        chunk_id    = CHUNK_ID,
        source_id   = SOURCE_ID,
        entities    = two_entities,
        duration_ms = 1.0,
    )

    engine = EdgeInferenceEngine(EdgeInferenceSettings(use_llm=False))

    async def run_500():
        for _ in range(500):
            await engine.infer(result, "chunk text")

    elapsed = benchmark(asyncio.run, run_500())
    assert benchmark.stats["mean"] < 5.0, (
        f"500 chunks (heuristic path) took {benchmark.stats['mean']:.2f}s — must be < 5s"
    )
```

---

### AC-5 — Stale relationships expired on `knowledge.source.synced`

```python
async def test_stale_relationships_expired_on_source_synced(
    mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store
):
    from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings
    from src.knowledge_graph.schemas.relationship import RelationshipExpirySettings

    consumer = GraphUpdaterConsumer(
        mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store,
        GraphUpdaterSettings(),
        expiry_settings=RelationshipExpirySettings(ttl_days=30),
    )
    consumer._producer = AsyncMock()

    from src.knowledge_sources.schemas.events import SourceSyncedEvent
    sync_event = SourceSyncedEvent(
        source_id        = SOURCE_ID,
        tenant_id        = "acme",
        job_id           = uuid4(),
        items_processed  = 42,
        synced_at        = datetime.now(tz=timezone.utc),
    )
    msg       = MagicMock()
    msg.topic = "knowledge.source.synced"
    msg.value = sync_event.model_dump()

    await consumer._handle_message(msg)

    mock_edge_store.expire_stale_relationships.assert_awaited_once()
    cutoff_arg = mock_edge_store.expire_stale_relationships.call_args.args[0]
    expected_cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
    assert abs((cutoff_arg - expected_cutoff).total_seconds()) < 5


def test_relationship_expiry_settings_ttl_delta():
    from src.knowledge_graph.schemas.relationship import RelationshipExpirySettings
    settings = RelationshipExpirySettings(ttl_days=7)
    assert settings.ttl_delta == timedelta(days=7)
```

---

### AC-6 — `knowledge.graph.updated` emitted after sync

```python
async def test_graph_updated_event_emitted_after_source_synced(
    mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store
):
    from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings
    import json

    consumer = GraphUpdaterConsumer(
        mock_entity_extractor, mock_edge_engine, mock_entity_store, mock_edge_store,
        GraphUpdaterSettings(),
    )
    mock_producer = AsyncMock()
    consumer._producer = mock_producer

    from src.knowledge_sources.schemas.events import SourceSyncedEvent
    sync_event = SourceSyncedEvent(
        source_id       = SOURCE_ID,
        tenant_id       = "acme",
        job_id          = uuid4(),
        items_processed = 10,
        synced_at       = datetime.now(tz=timezone.utc),
    )
    msg       = MagicMock()
    msg.topic = "knowledge.source.synced"
    msg.value = sync_event.model_dump()

    await consumer._handle_message(msg)

    mock_producer.send_and_wait.assert_awaited_once()
    topic   = mock_producer.send_and_wait.call_args.args[0]
    payload = mock_producer.send_and_wait.call_args.kwargs["value"]
    assert topic == "knowledge.graph.updated"
    assert payload["event_type"]  == "knowledge_graph_updated"
    assert payload["source_id"]   == str(SOURCE_ID)
    assert "relationships_expired" in payload


# Edge inference: no self-loop
def test_graph_relationship_rejects_self_loop():
    from src.knowledge_graph.schemas.relationship import GraphRelationship
    from src.knowledge_graph.schemas.edge         import EdgeType
    import pytest
    from pydantic import ValidationError

    eid = "a" * 16
    with pytest.raises(ValidationError, match="Self-loop"):
        GraphRelationship.create(eid, eid, EdgeType.REFERENCES, SOURCE_ID, CHUNK_ID)
```

## Acceptance Criteria

- [ ] All 6 AC-level tests pass in CI without live Kafka or Neo4j
- [ ] `test_tombstone_removes_entity_relationships` confirms `merge_relationships` is NOT called on tombstone
- [ ] `test_stale_relationships_expired_on_source_synced` verifies cutoff is within 5 s of `now - ttl_days`
- [ ] `test_graph_updated_event_emitted_after_source_synced` verifies correct topic and `event_type`
- [ ] `test_graph_relationship_rejects_self_loop` confirms `model_validator` prevents self-loops
- [ ] Benchmark test gated behind `--benchmark-only` flag (excluded from default `pytest` run)

## Dependencies

- TASK-US030-01 (`GraphRelationship`, `TombstoneEvent`, `GraphUpdatedEvent`, `RelationshipExpirySettings`)
- TASK-US030-02 (`EdgeInferenceEngine`)
- TASK-US030-03 (`Neo4jEdgeStore`)
- TASK-US030-04 (`GraphUpdaterConsumer`, `GraphUpdaterSettings`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests use `AsyncMock`; no live services required in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
