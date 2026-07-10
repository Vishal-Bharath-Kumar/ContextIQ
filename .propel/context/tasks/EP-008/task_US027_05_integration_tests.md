# TASK-US027-05 — Integration Tests Covering All 7 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US027-05 |
| User Story | US-027 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the integration and unit test suite covering all 7 US-027 acceptance criteria: Kafka event consumption, embedding model dispatch, Qdrant vector upsert, OpenSearch keyword index, PostgreSQL chunk metadata persistence, throughput floor, and stale embedding deletion within SLA.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, pytest-benchmark, `AsyncMock`, `unittest.mock`

**File locations:**
- `tests/indexing/test_indexing_pipeline.py` — AC-1 through AC-6 (pipeline integration)
- `tests/indexing/test_deletion_handler.py` — AC-7 (stale embedding deletion)
- `tests/indexing/test_consumer_routing.py` — AC-1 Kafka consumer routing

---

### Shared fixtures

```python
# tests/indexing/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid          import uuid4
from datetime      import datetime, timezone

from src.indexing.schemas.chunk  import ChunkPayload

SOURCE_ID = uuid4()
TENANT_ID = "acme"

@pytest.fixture
def make_chunk():
    def _make(text: str = "hello world", token_count: int = 10) -> ChunkPayload:
        return ChunkPayload(
            source_id   = SOURCE_ID,
            tenant_id   = TENANT_ID,
            document_id = f"github:org/repo:{uuid4().hex[:8]}",
            text        = text,
            token_count = token_count,
        )
    return _make

@pytest.fixture
def mock_qdrant():
    q = AsyncMock()
    q.ensure_collection = AsyncMock()
    q.upsert            = AsyncMock()
    q.delete_by_document= AsyncMock()
    return q

@pytest.fixture
def mock_opensearch():
    o = AsyncMock()
    o.ensure_index      = AsyncMock()
    o.bulk_index        = AsyncMock()
    o.delete_by_document= AsyncMock()
    return o

@pytest.fixture
def mock_chunk_repo():
    r = AsyncMock()
    r.upsert_batch       = AsyncMock()
    r.list_by_document   = AsyncMock(return_value=[])
    r.delete_by_document = AsyncMock(return_value=0)
    return r

@pytest.fixture
def mock_embedder(make_chunk):
    from src.indexing.schemas.chunk import IndexedChunk
    async def _embed(chunks):
        return [IndexedChunk(payload=c, vector=[0.1] * 1536, model_id="text-embedding-3-small")
                for c in chunks]
    e = AsyncMock()
    e.embed_batch = AsyncMock(side_effect=_embed)
    return e

@pytest.fixture
def mock_connector(make_chunk):
    c = AsyncMock()
    c.get_chunks = AsyncMock(return_value=[make_chunk() for _ in range(10)])
    return c

@pytest.fixture
def mock_registry(mock_connector):
    r = MagicMock()
    r.get = MagicMock(return_value=mock_connector)
    return r
```

---

### AC-1 — Kafka consumer dispatches `knowledge_source_synced` to pipeline

```python
# tests/indexing/test_consumer_routing.py
async def test_consumer_routes_synced_event_to_pipeline(mock_registry, mock_embedder,
                                                         mock_qdrant, mock_opensearch,
                                                         mock_chunk_repo):
    from src.indexing.pipeline          import IndexingPipeline
    from src.indexing.consumer          import IndexingConsumer
    from src.indexing.stores.deletion_handler import DeletionHandler

    pipeline  = IndexingPipeline(mock_embedder, mock_qdrant, mock_opensearch,
                                  mock_chunk_repo, mock_registry)
    deletion  = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    consumer  = IndexingConsumer(pipeline=pipeline, deletion_handler=deletion)

    msg = MagicMock()
    msg.value = {
        "event_type": "knowledge_source_synced",
        "source_id":  str(SOURCE_ID),
        "tenant_id":  TENANT_ID,
        "job_id":     str(uuid4()),
        "items_processed": 10,
        "synced_at":  datetime.now(tz=timezone.utc).isoformat(),
    }
    await consumer._handle_message(msg)
    mock_embedder.embed_batch.assert_awaited_once()


async def test_consumer_routes_deleted_event_to_deletion_handler(mock_qdrant, mock_opensearch,
                                                                    mock_chunk_repo, mock_registry,
                                                                    mock_embedder):
    from src.indexing.pipeline          import IndexingPipeline
    from src.indexing.consumer          import IndexingConsumer
    from src.indexing.stores.deletion_handler import DeletionHandler

    doc_id    = "github:org/repo:abc123"
    pipeline  = IndexingPipeline(mock_embedder, mock_qdrant, mock_opensearch,
                                  mock_chunk_repo, mock_registry)
    deletion  = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    consumer  = IndexingConsumer(pipeline=pipeline, deletion_handler=deletion)

    msg = MagicMock()
    msg.value = {
        "event_type":  "knowledge_document_deleted",
        "source_id":   str(SOURCE_ID),
        "tenant_id":   TENANT_ID,
        "document_id": doc_id,
    }
    await consumer._handle_message(msg)
    mock_chunk_repo.list_by_document.assert_awaited_once_with(doc_id)


async def test_consumer_skips_unknown_event_type_without_crash(mock_registry, mock_embedder,
                                                                mock_qdrant, mock_opensearch,
                                                                mock_chunk_repo):
    from src.indexing.pipeline          import IndexingPipeline
    from src.indexing.consumer          import IndexingConsumer
    from src.indexing.stores.deletion_handler import DeletionHandler

    pipeline = IndexingPipeline(mock_embedder, mock_qdrant, mock_opensearch,
                                 mock_chunk_repo, mock_registry)
    deletion = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    consumer = IndexingConsumer(pipeline=pipeline, deletion_handler=deletion)

    msg = MagicMock()
    msg.value = {"event_type": "totally_unknown_event"}
    await consumer._handle_message(msg)    # must not raise
    mock_embedder.embed_batch.assert_not_awaited()
```

---

### AC-2 — Embedding model dispatched and propagated

```python
# tests/indexing/test_indexing_pipeline.py
async def test_embedding_model_id_propagated_to_chunk_metadata(mock_registry, mock_qdrant,
                                                                 mock_opensearch, mock_chunk_repo):
    from src.indexing.embedding.service import EmbeddingService, EmbeddingSettings
    from src.indexing.pipeline          import IndexingPipeline

    with patch("litellm.aembedding", new_callable=AsyncMock) as mock_litellm:
        mock_litellm.return_value = MagicMock(
            data=[{"embedding": [0.0] * 1536} for _ in range(10)]
        )
        embedder  = EmbeddingService(EmbeddingSettings(model_id="text-embedding-3-small"))
        pipeline  = IndexingPipeline(embedder, mock_qdrant, mock_opensearch,
                                      mock_chunk_repo, mock_registry)
        await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    saved = mock_chunk_repo.upsert_batch.call_args.args[0]
    assert all(c.embedding_model == "text-embedding-3-small" for c in saved)
```

---

### AC-3 — Qdrant upsert with correct collection name

```python
async def test_qdrant_collection_name_format(mock_registry, mock_embedder,
                                               mock_qdrant, mock_opensearch, mock_chunk_repo):
    from src.indexing.pipeline           import IndexingPipeline
    from src.indexing.stores.qdrant_indexer import collection_name

    pipeline = IndexingPipeline(mock_embedder, mock_qdrant, mock_opensearch,
                                  mock_chunk_repo, mock_registry)
    await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    expected = collection_name(SOURCE_ID, TENANT_ID)
    mock_qdrant.ensure_collection.assert_awaited_once_with(SOURCE_ID, TENANT_ID)
    # confirm format: {hex}_{tenant_id}
    assert expected == f"{SOURCE_ID.hex}_{TENANT_ID}"
```

---

### AC-4 — OpenSearch bulk index called

```python
async def test_opensearch_bulk_index_called(mock_registry, mock_embedder,
                                              mock_qdrant, mock_opensearch, mock_chunk_repo):
    from src.indexing.pipeline import IndexingPipeline

    pipeline = IndexingPipeline(mock_embedder, mock_qdrant, mock_opensearch,
                                  mock_chunk_repo, mock_registry)
    await pipeline.run_for_source(SOURCE_ID, TENANT_ID)
    mock_opensearch.bulk_index.assert_awaited_once()
    args = mock_opensearch.bulk_index.call_args
    assert args.kwargs["tenant_id"] == TENANT_ID
```

---

### AC-5 — PostgreSQL chunk metadata persisted

```python
async def test_postgresql_chunk_metadata_persisted(mock_registry, mock_embedder,
                                                     mock_qdrant, mock_opensearch, mock_chunk_repo):
    from src.indexing.pipeline           import IndexingPipeline
    from src.indexing.schemas.chunk      import ChunkMetadata

    pipeline = IndexingPipeline(mock_embedder, mock_qdrant, mock_opensearch,
                                  mock_chunk_repo, mock_registry)
    count = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    mock_chunk_repo.upsert_batch.assert_awaited_once()
    saved: list[ChunkMetadata] = mock_chunk_repo.upsert_batch.call_args.args[0]
    assert len(saved) == count
    assert all(isinstance(c, ChunkMetadata) for c in saved)
    assert all(c.source_id == SOURCE_ID for c in saved)
    assert all(c.indexed_at is not None for c in saved)
```

---

### AC-6 — Throughput benchmark: ≥ 1,000 chunks/min

```python
# pytest-benchmark — run with: pytest --benchmark-only
def test_embedding_throughput_benchmark(benchmark, make_chunk):
    """
    Validates that embedding 1 000 chunks takes ≤ 60 s wall-clock time using
    the local fastembed model (avoids OpenAI latency in CI).
    """
    import asyncio
    from src.indexing.embedding.service   import EmbeddingService, EmbeddingSettings
    from src.indexing.embedding.fastembed_provider import FastEmbedProvider

    chunks = [make_chunk(text=f"chunk text {i}" * 5) for i in range(1_000)]

    with patch.object(FastEmbedProvider, "embed", return_value=[[0.1] * 384] * len(chunks)):
        settings = EmbeddingSettings(use_local_model=True, concurrency=4, batch_size=256)
        service  = EmbeddingService(settings)
        result   = benchmark(asyncio.run, service.embed_batch(chunks))

    assert len(result) == 1_000
    assert benchmark.stats["mean"] < 60.0, (
        f"Embedding 1 000 chunks took {benchmark.stats['mean']:.1f}s — must be < 60s"
    )
```

---

### AC-7 — Stale embedding deletion

```python
# tests/indexing/test_deletion_handler.py
async def test_deletion_handler_calls_all_three_stores(mock_qdrant, mock_opensearch, mock_chunk_repo):
    from uuid                                   import uuid4
    from src.indexing.stores.deletion_handler   import DeletionHandler
    from src.indexing.models.chunk              import ChunkRecord

    doc_id = "confluence:SPACE:12345"
    chunk_records = [MagicMock(spec=ChunkRecord, chunk_id=uuid4()) for _ in range(3)]
    mock_chunk_repo.list_by_document = AsyncMock(return_value=chunk_records)

    handler = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    await handler.handle(doc_id, SOURCE_ID, TENANT_ID)

    mock_qdrant.delete_by_document.assert_awaited_once()
    mock_opensearch.delete_by_document.assert_awaited_once_with(doc_id, TENANT_ID)
    mock_chunk_repo.delete_by_document.assert_awaited_once_with(doc_id)


async def test_deletion_handler_no_qdrant_call_when_no_chunks(mock_qdrant, mock_opensearch,
                                                                mock_chunk_repo):
    from src.indexing.stores.deletion_handler import DeletionHandler

    mock_chunk_repo.list_by_document = AsyncMock(return_value=[])

    handler = DeletionHandler(mock_chunk_repo, mock_qdrant, mock_opensearch)
    await handler.handle("doc:none", SOURCE_ID, TENANT_ID)
    mock_qdrant.delete_by_document.assert_not_awaited()
```

---

### Parallel `asyncio.gather` assertion

```python
async def test_pipeline_uses_gather_for_store_writes(mock_registry, mock_embedder,
                                                       mock_qdrant, mock_opensearch, mock_chunk_repo):
    """
    Verify that ensure_collection + ensure_index are called concurrently,
    and that qdrant.upsert + opensearch.bulk_index are called concurrently,
    by confirming both are awaited within a single event-loop tick.
    """
    from src.indexing.pipeline import IndexingPipeline
    import asyncio

    call_order: list[str] = []

    async def record_qdrant_ensure(*a, **kw):
        call_order.append("qdrant_ensure")
    async def record_os_ensure(*a, **kw):
        call_order.append("os_ensure")
    async def record_qdrant_upsert(*a, **kw):
        call_order.append("qdrant_upsert")
    async def record_os_bulk(*a, **kw):
        call_order.append("os_bulk")

    mock_qdrant.ensure_collection = record_qdrant_ensure
    mock_qdrant.upsert            = record_qdrant_upsert
    mock_opensearch.ensure_index  = record_os_ensure
    mock_opensearch.bulk_index    = record_os_bulk

    pipeline = IndexingPipeline(mock_embedder, mock_qdrant, mock_opensearch,
                                  mock_chunk_repo, mock_registry)
    await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

    # Both ensures must appear before both writes
    ensure_indices = {call_order.index("qdrant_ensure"), call_order.index("os_ensure")}
    write_indices  = {call_order.index("qdrant_upsert"), call_order.index("os_bulk")}
    assert max(ensure_indices) < min(write_indices)
```

## Acceptance Criteria

- [ ] All AC-level tests pass in CI without live Kafka, Qdrant, OpenSearch, or PostgreSQL
- [ ] `test_deletion_handler_no_qdrant_call_when_no_chunks` confirms no empty-list Qdrant call
- [ ] `test_embedding_throughput_benchmark` passes with `mean < 60s` using mocked fastembed
- [ ] `test_consumer_skips_unknown_event_type_without_crash` confirms poison-pill safety
- [ ] `test_postgresql_chunk_metadata_persisted` verifies `indexed_at` is set on every chunk

## Dependencies

- TASK-US027-01 (`ChunkPayload`, `ChunkMetadata`, `ChunkRepository`)
- TASK-US027-02 (`EmbeddingService`, `EmbeddingSettings`, `FastEmbedProvider`)
- TASK-US027-03 (`QdrantIndexer`, `OpenSearchIndexer`, `DeletionHandler`)
- TASK-US027-04 (`IndexingPipeline`, `IndexingConsumer`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests use `AsyncMock`; no live services required in CI
- [ ] Benchmark test gated behind `--benchmark-only` flag (excluded from default `pytest` run)
- [ ] `mypy --strict` passes; no `ruff` lint errors
