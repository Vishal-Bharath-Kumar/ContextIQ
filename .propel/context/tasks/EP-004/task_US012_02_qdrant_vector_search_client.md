# TASK-US012-02 — Qdrant ANN Vector Search Client

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US012-02 |
| User Story | US-012 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement `QdrantSearchClient`, the async client that embeds the query using the configured embedding model, executes an Approximate Nearest Neighbour (ANN) vector search against the Qdrant collection, and returns an ordered list of `RetrievedChunk` instances. The client targets TR-014 (Qdrant) and operates within the parallel search budget of the `HybridSearchEngine` (TASK-US012-05).

## Implementation Details

**Technology:** Python 3.11+, `qdrant-client[fastembed]>=1.9`, `fastembed>=0.3`, Qdrant Cloud or self-hosted

**File locations:**
- `src/retrieval/clients/qdrant_client.py` — `QdrantSearchClient` class
- `src/retrieval/embedding/embedder.py` — `QueryEmbedder` singleton
- `tests/retrieval/clients/test_qdrant_client.py`

**`QueryEmbedder` singleton:**

```python
# src/retrieval/embedding/embedder.py
from fastembed import TextEmbedding

class QueryEmbedder:
    """Singleton embedding wrapper — model is loaded once at process start."""

    _instance: "QueryEmbedder | None" = None

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self._model = TextEmbedding(model_name=model_name)

    @classmethod
    def get(cls) -> "QueryEmbedder":
        if cls._instance is None:
            cls._instance = QueryEmbedder()
        return cls._instance

    def embed(self, text: str) -> list[float]:
        return list(self._model.embed([text]))[0].tolist()
```

**`QdrantSearchClient`:**

```python
# src/retrieval/clients/qdrant_client.py
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import ScoredPoint
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk, ChunkMetadata, make_chunk_id
from src.retrieval.embedding.embedder import QueryEmbedder

class QdrantSearchClient:
    COLLECTION: str   # set from settings: QDRANT_COLLECTION_NAME
    VECTOR_SIZE: int = 384   # bge-small-en-v1.5 dimensionality

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client   = client
        self._embedder = QueryEmbedder.get()

    async def search(
        self,
        query:      str,
        source_id:  str,
        top_k:      int = 20,
    ) -> list[RetrievedChunk]:
        query_vector = self._embedder.embed(query)

        hits: list[ScoredPoint] = await self._client.search(
            collection_name = self.COLLECTION,
            query_vector    = query_vector,
            query_filter    = self._source_filter(source_id),
            limit           = top_k,
            with_payload    = True,
            with_vectors    = False,
        )

        return [self._to_chunk(hit, source_id) for hit in hits]

    @staticmethod
    def _source_filter(source_id: str):
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        return Filter(
            must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
        )

    @staticmethod
    def _to_chunk(hit: ScoredPoint, source_id: str) -> RetrievedChunk:
        payload  = hit.payload or {}
        meta     = payload.get("metadata", {})
        chunk_idx = payload.get("chunk_index", 0)
        return RetrievedChunk(
            chunk_id   = make_chunk_id(source_id, meta.get("file_path", ""), chunk_idx),
            source_id  = source_id,
            content    = payload.get("content", ""),
            score      = min(max(float(hit.score), 0.0), 1.0),  # cosine similarity already 0–1
            search_mode = "vector",
            metadata   = ChunkMetadata(
                file_path  = meta.get("file_path", ""),
                timestamp  = meta.get("timestamp"),
                author     = meta.get("author", ""),
                url        = meta.get("url"),
                chunk_index = chunk_idx,
            ),
        )
```

**Environment variables:**

```
QDRANT_URL=https://<cluster>.qdrant.io:6333
QDRANT_API_KEY=<secret>
QDRANT_COLLECTION_NAME=contextiq_chunks
```

**Connection management:**
- `AsyncQdrantClient` is constructed once at startup and injected via FastAPI dependency — not per-request
- gRPC transport preferred over REST for search calls (`prefer_grpc=True`) to reduce serialisation overhead

## Acceptance Criteria

- [ ] `QdrantSearchClient.search()` returns a `list[RetrievedChunk]` ordered by descending `score`
- [ ] `search_mode` is `"vector"` for all chunks returned by this client
- [ ] Results are filtered to `source_id` via Qdrant payload filter — no cross-source leakage
- [ ] `score` is clamped to `[0.0, 1.0]` regardless of raw cosine similarity value
- [ ] `QueryEmbedder` is instantiated exactly once per process (singleton pattern enforced by unit test)
- [ ] Client is tested against a mocked `AsyncQdrantClient` — no live Qdrant connection in CI

## Dependencies

- TASK-US012-01 (`RetrievedChunk` and `ChunkMetadata` schemas, `make_chunk_id()`)
- EP-008 (Qdrant collection populated with indexed embeddings — required for integration tests)
- EP-DATA-001 (Qdrant infrastructure — `QDRANT_URL` and API key available in staging)
- TR-014 (Qdrant technology spec)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for `src/retrieval/clients/qdrant_client.py`
- [ ] `AsyncQdrantClient` constructed once at app startup — not per search call
- [ ] gRPC transport enabled via `prefer_grpc=True` constructor argument
- [ ] `mypy --strict` passes; no `ruff` lint errors
