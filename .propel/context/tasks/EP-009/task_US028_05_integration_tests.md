# TASK-US028-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US028-05 |
| User Story | US-028 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the integration and unit test suite covering all 6 US-028 acceptance criteria: Kafka event trigger, 7-type entity extraction, Neo4j node properties, deterministic deduplication, 500 ms extraction budget, and retry/DLQ on failure.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `AsyncMock`, `unittest.mock`

**File locations:**
- `tests/knowledge_graph/test_entity_schema.py` — AC-4 (deterministic `entity_id`)
- `tests/knowledge_graph/test_entity_extractor.py` — AC-2, AC-5 (extraction + timing)
- `tests/knowledge_graph/test_neo4j_entity_store.py` — AC-3, AC-4 (node write + dedup)
- `tests/knowledge_graph/test_entity_consumer.py` — AC-1, AC-6 (Kafka routing + retry)

---

### Shared fixtures

```python
# tests/knowledge_graph/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid          import uuid4
from datetime      import datetime, timezone

from src.knowledge_graph.schemas.entity import EntityType, ExtractedEntity, make_entity_id
from src.knowledge_graph.schemas.events import ChunkIndexedEvent

SOURCE_ID = uuid4()
CHUNK_ID  = uuid4()

@pytest.fixture
def chunk_indexed_event():
    return ChunkIndexedEvent(
        chunk_id        = CHUNK_ID,
        source_id       = SOURCE_ID,
        tenant_id       = "acme",
        document_id     = "github:org/repo:abc123",
        text            = "The auth-service depends on the user-repository owned by @alice.",
        token_count     = 14,
        embedding_model = "text-embedding-3-small",
        indexed_at      = datetime.now(tz=timezone.utc),
    )

@pytest.fixture
def make_entity():
    def _make(entity_type=EntityType.SERVICE, name="auth-service"):
        canonical = name.strip().lower()
        return ExtractedEntity(
            entity_id      = make_entity_id(entity_type, canonical),
            entity_type    = entity_type,
            name           = name,
            canonical_name = canonical,
            source_id      = SOURCE_ID,
            chunk_id       = CHUNK_ID,
            created_at     = datetime.now(tz=timezone.utc),
        )
    return _make
```

---

### AC-1 — Kafka consumer triggers extraction on `knowledge.chunk.indexed`

```python
# tests/knowledge_graph/test_entity_consumer.py
async def test_consumer_triggers_extractor_on_chunk_indexed(chunk_indexed_event, make_entity):
    from src.knowledge_graph.consumer import EntityConsumer, EntityConsumerSettings
    from src.knowledge_graph.schemas.entity import EntityExtractionResult

    mock_extractor   = AsyncMock()
    mock_neo4j_store = AsyncMock()
    mock_extractor._settings = MagicMock(model_id="gpt-4o-mini")
    mock_extractor.extract = AsyncMock(return_value=EntityExtractionResult(
        chunk_id    = CHUNK_ID,
        source_id   = SOURCE_ID,
        entities    = [make_entity()],
        duration_ms = 250.0,
    ))

    consumer = EntityConsumer(mock_extractor, mock_neo4j_store)
    msg = MagicMock()
    msg.topic = "knowledge.chunk.indexed"
    msg.value = chunk_indexed_event.model_dump()

    await consumer._handle_message(msg)

    mock_extractor.extract.assert_awaited_once()
    mock_neo4j_store.merge_entities.assert_awaited_once()
```

---

### AC-2 — All 7 entity types extracted and returned

```python
# tests/knowledge_graph/test_entity_extractor.py
async def test_extractor_returns_all_seven_entity_types(chunk_indexed_event):
    from src.knowledge_graph.extraction.extractor import EntityExtractor, ExtractionSettings
    from src.knowledge_graph.schemas.entity       import EntityType

    llm_payload = {
        "entities": [
            {"entity_type": t.value, "name": f"test-{t.value.lower()}",
             "canonical_name": f"test-{t.value.lower()}", "properties": {}}
            for t in EntityType
        ]
    }
    import json
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(llm_payload)))]

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        extractor = EntityExtractor(ExtractionSettings(model_id="gpt-4o-mini"))
        result    = await extractor.extract(chunk_indexed_event)

    returned_types = {e.entity_type for e in result.entities}
    assert returned_types == set(EntityType)
```

---

### AC-3 — Neo4j node has required properties

```python
# tests/knowledge_graph/test_neo4j_entity_store.py
async def test_neo4j_node_has_required_properties(make_entity):
    from src.knowledge_graph.stores.neo4j_store import Neo4jEntityStore, Neo4jSettings

    written_batches: list[dict] = []

    mock_session = AsyncMock()
    async def capture_run(cypher, **kwargs):
        written_batches.extend(kwargs.get("batch", []))
    mock_session.run = capture_run
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)

    with patch("src.knowledge_graph.stores.neo4j_store.AsyncGraphDatabase.driver",
               return_value=mock_driver):
        store  = Neo4jEntityStore(Neo4jSettings())
        entity = make_entity()
        await store.merge_entities([entity])

    assert len(written_batches) == 1
    props = written_batches[0]
    for required_field in ("entity_id", "type", "name", "source_id", "created_at"):
        assert required_field in props, f"Missing required property: {required_field}"
```

---

### AC-4 — Deterministic `entity_id` deduplication

```python
# tests/knowledge_graph/test_entity_schema.py
def test_entity_id_is_deterministic():
    from src.knowledge_graph.schemas.entity import make_entity_id, EntityType
    id1 = make_entity_id(EntityType.SERVICE, "auth-service")
    id2 = make_entity_id(EntityType.SERVICE, "auth-service")
    assert id1 == id2

def test_entity_id_normalises_whitespace():
    from src.knowledge_graph.schemas.entity import make_entity_id, EntityType
    assert (
        make_entity_id(EntityType.SERVICE, "  Auth Service  ")
        == make_entity_id(EntityType.SERVICE, "auth service")
    )

def test_entity_id_differs_by_type():
    from src.knowledge_graph.schemas.entity import make_entity_id, EntityType
    svc  = make_entity_id(EntityType.SERVICE,    "auth")
    repo = make_entity_id(EntityType.REPOSITORY, "auth")
    assert svc != repo

def test_entity_id_mismatch_raises_validation_error(make_entity):
    from pydantic import ValidationError
    from src.knowledge_graph.schemas.entity import ExtractedEntity, EntityType
    import pytest
    with pytest.raises(ValidationError, match="entity_id mismatch"):
        ExtractedEntity(
            entity_id      = "0000000000000000",   # wrong ID
            entity_type    = EntityType.SERVICE,
            name           = "auth-service",
            canonical_name = "auth-service",
            source_id      = SOURCE_ID,
            chunk_id       = CHUNK_ID,
            created_at     = datetime.now(tz=timezone.utc),
        )
```

---

### AC-5 — Extraction within 500 ms budget (with hard 2 s timeout guard)

```python
# tests/knowledge_graph/test_entity_extractor.py (continued)
async def test_extractor_raises_timeout_on_slow_llm(chunk_indexed_event):
    from src.knowledge_graph.extraction.extractor import EntityExtractor, ExtractionSettings
    import asyncio

    async def slow_llm(*args, **kwargs):
        await asyncio.sleep(10)   # simulate hung LLM

    with patch("litellm.acompletion", side_effect=slow_llm), \
         pytest.raises(asyncio.TimeoutError):
        extractor = EntityExtractor(ExtractionSettings(timeout_s=0.1))
        await extractor.extract(chunk_indexed_event)


async def test_extractor_records_duration_ms(chunk_indexed_event):
    import json
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(
        content=json.dumps({"entities": []})
    ))]
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        from src.knowledge_graph.extraction.extractor import EntityExtractor
        result = await EntityExtractor().extract(chunk_indexed_event)
    assert result.duration_ms > 0
```

---

### AC-6 — Retry and DLQ on failure

```python
# tests/knowledge_graph/test_entity_consumer.py (continued)
async def test_consumer_requeues_on_first_failure(chunk_indexed_event):
    from src.knowledge_graph.consumer import EntityConsumer, EntityConsumerSettings

    mock_extractor = AsyncMock()
    mock_extractor._settings = MagicMock(model_id="gpt-4o-mini")
    mock_extractor.extract = AsyncMock(side_effect=RuntimeError("LLM error"))

    mock_neo4j = AsyncMock()
    mock_producer = AsyncMock()

    consumer = EntityConsumer(mock_extractor, mock_neo4j,
                               EntityConsumerSettings(max_retries=3))
    consumer._producer = mock_producer

    msg = MagicMock()
    msg.topic = "knowledge.chunk.indexed"
    msg.value = chunk_indexed_event.model_dump()

    await consumer._handle_message(msg)

    # Should re-queue to retry topic, not DLQ
    mock_producer.send_and_wait.assert_awaited_once()
    topic_sent = mock_producer.send_and_wait.call_args.args[0]
    assert topic_sent == "knowledge.chunk.indexed.retry"


async def test_consumer_sends_to_dlq_after_max_retries(chunk_indexed_event):
    from src.knowledge_graph.consumer import EntityConsumer, EntityConsumerSettings

    mock_extractor = AsyncMock()
    mock_extractor._settings = MagicMock(model_id="gpt-4o-mini")
    mock_extractor.extract = AsyncMock(side_effect=RuntimeError("persistent error"))

    mock_neo4j   = AsyncMock()
    mock_producer = AsyncMock()

    consumer = EntityConsumer(mock_extractor, mock_neo4j,
                               EntityConsumerSettings(max_retries=3))
    consumer._producer = mock_producer

    # Simulate arriving at the retry topic at max attempt
    from src.knowledge_graph.schemas.events import ChunkRetryEnvelope
    envelope = ChunkRetryEnvelope(attempt=3, original=chunk_indexed_event)
    msg = MagicMock()
    msg.topic = "knowledge.chunk.indexed.retry"
    msg.value = envelope.model_dump()

    await consumer._handle_message(msg)

    mock_producer.send_and_wait.assert_awaited_once()
    topic_sent = mock_producer.send_and_wait.call_args.args[0]
    assert topic_sent == "knowledge.entity.extraction.dlq"


async def test_consumer_commits_offset_on_dlq(chunk_indexed_event):
    """Offset is committed even for DLQ messages — prevents infinite re-delivery."""
    from src.knowledge_graph.consumer import EntityConsumer, EntityConsumerSettings

    mock_extractor = AsyncMock()
    mock_extractor._settings = MagicMock(model_id="gpt-4o-mini")
    mock_extractor.extract = AsyncMock(side_effect=RuntimeError("fail"))

    consumer = EntityConsumer(mock_extractor, AsyncMock(),
                               EntityConsumerSettings(max_retries=1))
    consumer._producer = AsyncMock()

    from src.knowledge_graph.schemas.events import ChunkRetryEnvelope
    envelope = ChunkRetryEnvelope(attempt=1, original=chunk_indexed_event)
    msg = MagicMock()
    msg.topic = "knowledge.chunk.indexed.retry"
    msg.value = envelope.model_dump()

    # Simulate run() committing after _handle_message
    mock_consumer = AsyncMock()
    consumer._consumer = mock_consumer
    await consumer._handle_message(msg)
    await mock_consumer.commit()
    mock_consumer.commit.assert_awaited_once()
```

## Acceptance Criteria

- [ ] All 6 AC-level tests pass in CI without live Kafka, Neo4j, or LLM
- [ ] `test_entity_id_mismatch_raises_validation_error` confirms `model_validator` enforcement
- [ ] `test_extractor_raises_timeout_on_slow_llm` confirms `asyncio.TimeoutError` propagation
- [ ] `test_consumer_sends_to_dlq_after_max_retries` confirms no further re-queue after exhaustion
- [ ] `test_consumer_commits_offset_on_dlq` confirms at-least-once + no-infinite-loop guarantee

## Dependencies

- TASK-US028-01 (`EntityType`, `ExtractedEntity`, `make_entity_id`, `ChunkIndexedEvent`, `ChunkRetryEnvelope`)
- TASK-US028-02 (`EntityExtractor`, `ExtractionSettings`)
- TASK-US028-03 (`Neo4jEntityStore`)
- TASK-US028-04 (`EntityConsumer`, `EntityConsumerSettings`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests use `AsyncMock`; no live services in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
