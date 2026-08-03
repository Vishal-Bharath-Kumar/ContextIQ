# TASK-US027-03 — `QdrantIndexer`, `OpenSearchIndexer`, and Stale-Embedding Deletion

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US027-03 |
| User Story | US-027 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `QdrantIndexer` (vector upsert into a collection named `{source_id}_{tenant_id}`, AC-3) and `OpenSearchIndexer` (BM25 keyword index, AC-4). Implement the `DeletionHandler` which consumes document deletion signals and removes stale embeddings from Qdrant and stale entries from OpenSearch and PostgreSQL within the 5-minute SLA (AC-7).

## Implementation Details

**Technology:** Python 3.11+, `qdrant-client[async]>=1.9`, `opensearch-py[async]>=2.4`, Pydantic v2

**File locations:**
- `src/indexing/stores/qdrant_indexer.py` — `QdrantIndexer`, `QdrantSettings`
- `src/indexing/stores/opensearch_indexer.py` — `OpenSearchIndexer`, `OpenSearchSettings`
- `src/indexing/stores/deletion_handler.py` — `DeletionHandler`
- `tests/indexing/test_qdrant_indexer.py`
- `tests/indexing/test_opensearch_indexer.py`

---

### `QdrantIndexer`

**`QdrantSettings`:**

```python
# src/indexing/stores/qdrant_indexer.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class QdrantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_", env_file=".env")

    url:        str = "http://localhost:6333"
    api_key:    str | None = None
    # Vector dimension — must match the embedding model output.
    # text-embedding-3-small=1536, BAAI/bge-small-en-v1.5=384
    vector_size: int = 1536
    # Qdrant batch upsert limit per call.
    batch_size:  int = 128
    distance:    str = "Cosine"   # "Cosine" | "Dot" | "Euclid"
```

**Collection naming:**

```python
def collection_name(source_id: UUID, tenant_id: str) -> str:
    # Format: <source_id_hex_no_dashes>_<tenant_id>
    # Qdrant collection names must match [a-zA-Z0-9_-]+
    return f"{source_id.hex}_{tenant_id}"
```

**`QdrantIndexer`:**

```python
# src/indexing/stores/qdrant_indexer.py (continued)
import asyncio
from uuid              import UUID
from qdrant_client             import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance, VectorParams, PointStruct, UpdateStatus,
)
from src.indexing.schemas.chunk import IndexedChunk

class QdrantIndexer:
    def __init__(self, settings: QdrantSettings | None = None) -> None:
        self._settings = settings or QdrantSettings()
        self._client   = AsyncQdrantClient(
            url     = self._settings.url,
            api_key = self._settings.api_key,
        )

    async def ensure_collection(self, source_id: UUID, tenant_id: str) -> None:
        """Create the collection if it does not already exist. Idempotent."""
        name = collection_name(source_id, tenant_id)
        exists = await self._client.collection_exists(name)
        if not exists:
            await self._client.create_collection(
                collection_name = name,
                vectors_config  = VectorParams(
                    size     = self._settings.vector_size,
                    distance = Distance[self._settings.distance],
                ),
            )

    async def upsert(self, chunks: list[IndexedChunk], source_id: UUID, tenant_id: str) -> None:
        """
        Upsert all indexed chunks into the Qdrant collection in batches of `batch_size`.
        Point ID is the chunk_id UUID (Qdrant natively supports UUID point IDs).
        """
        name    = collection_name(source_id, tenant_id)
        batches = [
            chunks[i : i + self._settings.batch_size]
            for i in range(0, len(chunks), self._settings.batch_size)
        ]
        for batch in batches:
            points = [
                PointStruct(
                    id      = str(c.payload.chunk_id),
                    vector  = c.vector,
                    payload = {
                        "source_id":   str(c.payload.source_id),
                        "tenant_id":   c.payload.tenant_id,
                        "document_id": c.payload.document_id,
                        "text":        c.payload.text,
                        **c.payload.metadata,
                    },
                )
                for c in batch
            ]
            result = await self._client.upsert(
                collection_name = name,
                points          = points,
                wait            = True,
            )
            if result.status != UpdateStatus.COMPLETED:
                raise RuntimeError(
                    f"Qdrant upsert returned unexpected status: {result.status}"
                )

    async def delete_by_document(
        self,
        document_id: str,
        source_id:   UUID,
        tenant_id:   str,
        chunk_ids:   list[UUID],
    ) -> None:
        """Delete all point IDs for a given document (stale embedding cleanup, AC-7)."""
        if not chunk_ids:
            return
        name = collection_name(source_id, tenant_id)
        await self._client.delete(
            collection_name = name,
            points_selector = [str(cid) for cid in chunk_ids],
            wait            = True,
        )
```

---

### `OpenSearchIndexer`

**`OpenSearchSettings`:**

```python
# src/indexing/stores/opensearch_indexer.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class OpenSearchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENSEARCH_", env_file=".env")

    url:          str = "http://localhost:9200"
    username:     str = "admin"
    password:     str = "admin"
    bulk_size:    int = 256
    # Index naming: contextiq_chunks_{tenant_id}
    index_prefix: str = "contextiq_chunks"
```

**Index naming:**

```python
def index_name(tenant_id: str) -> str:
    return f"contextiq_chunks_{tenant_id}"
```

**`OpenSearchIndexer`:**

```python
# src/indexing/stores/opensearch_indexer.py (continued)
from opensearchpy import AsyncOpenSearch, helpers
from src.indexing.schemas.chunk import IndexedChunk

class OpenSearchIndexer:
    def __init__(self, settings: OpenSearchSettings | None = None) -> None:
        self._settings = settings or OpenSearchSettings()
        self._client   = AsyncOpenSearch(
            hosts             = [self._settings.url],
            http_auth         = (self._settings.username, self._settings.password),
            use_ssl           = self._settings.url.startswith("https"),
            verify_certs      = False,   # override in production via settings
        )

    async def ensure_index(self, tenant_id: str) -> None:
        name = index_name(tenant_id)
        if not await self._client.indices.exists(index=name):
            await self._client.indices.create(
                index=name,
                body={
                    "mappings": {
                        "properties": {
                            "chunk_id":   {"type": "keyword"},
                            "source_id":  {"type": "keyword"},
                            "document_id":{"type": "keyword"},
                            "text":       {"type": "text",    "analyzer": "english"},
                            "metadata":   {"type": "object",  "dynamic": True},
                        }
                    }
                },
            )

    async def bulk_index(self, chunks: list[IndexedChunk], tenant_id: str) -> None:
        """Bulk index chunk text and metadata for BM25 search."""
        name    = index_name(tenant_id)
        actions = [
            {
                "_index": name,
                "_id":    str(c.payload.chunk_id),
                "_source": {
                    "chunk_id":    str(c.payload.chunk_id),
                    "source_id":   str(c.payload.source_id),
                    "document_id": c.payload.document_id,
                    "text":        c.payload.text,
                    "metadata":    c.payload.metadata,
                },
            }
            for c in chunks
        ]
        await helpers.async_bulk(self._client, actions)

    async def delete_by_document(self, document_id: str, tenant_id: str) -> None:
        """Delete all entries for a given document_id (AC-7)."""
        name = index_name(tenant_id)
        await self._client.delete_by_query(
            index = name,
            body  = {"query": {"term": {"document_id": document_id}}},
        )
```

---

### `DeletionHandler` (AC-7 — stale embedding removal)

Stale embeddings arise when a document is deleted from the source (e.g. a GitHub file is removed). The deletion signal is delivered via a Kafka topic `knowledge.document.deleted`. The handler must complete cleanup within 5 minutes.

```python
# src/indexing/stores/deletion_handler.py
from uuid     import UUID
from datetime import datetime, timezone

from src.indexing.repositories.chunk_repository import ChunkRepository
from src.indexing.stores.qdrant_indexer         import QdrantIndexer
from src.indexing.stores.opensearch_indexer     import OpenSearchIndexer

class DeletionHandler:
    def __init__(
        self,
        chunk_repo:    ChunkRepository,
        qdrant:        QdrantIndexer,
        opensearch:    OpenSearchIndexer,
    ) -> None:
        self._chunk_repo  = chunk_repo
        self._qdrant      = qdrant
        self._opensearch  = opensearch

    async def handle(
        self,
        document_id: str,
        source_id:   UUID,
        tenant_id:   str,
    ) -> None:
        """
        1. Look up all chunk_ids for the document in PostgreSQL.
        2. Delete point IDs from Qdrant.
        3. Delete docs from OpenSearch.
        4. Delete rows from PostgreSQL.
        All three stores are updated in a single invocation; partial failure is safe
        because the caller re-delivers the event on retry.
        """
        records   = await self._chunk_repo.list_by_document(document_id)
        chunk_ids = [r.chunk_id for r in records]

        # Stores are updated in dependency order: vector store first (most expensive
        # to re-create), then keyword store, then metadata.
        await self._qdrant.delete_by_document(document_id, source_id, tenant_id, chunk_ids)
        await self._opensearch.delete_by_document(document_id, tenant_id)
        await self._chunk_repo.delete_by_document(document_id)
```

**5-minute SLA rationale:**

The Kafka consumer processes `knowledge.document.deleted` events immediately upon receipt (no scheduled batch). Qdrant `delete` with `wait=True` completes in < 200 ms for up to 2,000 points. OpenSearch `delete_by_query` typically completes in < 500 ms. PostgreSQL `DELETE … WHERE document_id = ?` with the index completes in < 50 ms. Total handler time is well within 5 minutes even under load.

## Acceptance Criteria

- [ ] `QdrantIndexer.ensure_collection()` is idempotent — calling it twice does not raise
- [ ] `QdrantIndexer.upsert()` splits 300 chunks into 3 batches (batch_size=128 default → 128+128+44)
- [ ] Collection name for `source_id=UUID("...")` and `tenant_id="acme"` matches `{hex}_acme` format
- [ ] `OpenSearchIndexer.bulk_index()` produces one `_bulk` HTTP call per `bulk_size` chunks
- [ ] `DeletionHandler.handle()` calls Qdrant delete, OpenSearch delete, and PostgreSQL delete in order
- [ ] `DeletionHandler.handle()` with zero existing chunks completes without error (no Qdrant call with empty IDs)
- [ ] `mypy --strict` passes

## Dependencies

- TASK-US027-01 (`ChunkRepository`, `ChunkPayload`, `IndexedChunk`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `AsyncMock` for `AsyncQdrantClient` and `AsyncOpenSearch`; no live stores in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
