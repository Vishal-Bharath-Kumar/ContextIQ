# TASK-US012-03 — OpenSearch BM25 Keyword Search Client

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US012-03 |
| User Story | US-012 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement `OpenSearchSearchClient`, the async client that executes a BM25 full-text keyword search against the OpenSearch index and returns an ordered list of `RetrievedChunk` instances. The client targets TR-015 (OpenSearch) and complements the Qdrant vector search path — both are dispatched concurrently by the `HybridSearchEngine` (TASK-US012-05).

## Implementation Details

**Technology:** Python 3.11+, `opensearch-py[async]>=2.4`, OpenSearch 2.x

**File locations:**
- `src/retrieval/clients/opensearch_client.py` — `OpenSearchSearchClient` class
- `tests/retrieval/clients/test_opensearch_client.py`

**`OpenSearchSearchClient`:**

```python
# src/retrieval/clients/opensearch_client.py
from opensearchpy import AsyncOpenSearch
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk, ChunkMetadata, make_chunk_id

class OpenSearchSearchClient:
    INDEX: str   # from settings: OPENSEARCH_INDEX_NAME

    def __init__(self, client: AsyncOpenSearch) -> None:
        self._client = client

    async def search(
        self,
        query:     str,
        source_id: str,
        top_k:     int = 20,
    ) -> list[RetrievedChunk]:
        response = await self._client.search(
            index = self.INDEX,
            body  = self._build_query(query, source_id, top_k),
        )
        return [
            self._to_chunk(hit, source_id)
            for hit in response["hits"]["hits"]
        ]

    @staticmethod
    def _build_query(query: str, source_id: str, top_k: int) -> dict:
        return {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query":  query,
                                "fields": ["content^2", "metadata.file_path"],
                                "type":   "best_fields",
                            }
                        }
                    ],
                    "filter": [
                        {"term": {"source_id": source_id}}
                    ],
                }
            },
            "_source": ["content", "source_id", "metadata"],
        }

    @staticmethod
    def _to_chunk(hit: dict, source_id: str) -> RetrievedChunk:
        src       = hit["_source"]
        meta      = src.get("metadata", {})
        chunk_idx = meta.get("chunk_index", 0)
        raw_score = hit.get("_score", 0.0)

        return RetrievedChunk(
            chunk_id   = make_chunk_id(source_id, meta.get("file_path", ""), chunk_idx),
            source_id  = source_id,
            content    = src.get("content", ""),
            score      = _normalise_bm25(raw_score),
            search_mode = "keyword",
            metadata   = ChunkMetadata(
                file_path   = meta.get("file_path", ""),
                timestamp   = meta.get("timestamp"),
                author      = meta.get("author", ""),
                url         = meta.get("url"),
                chunk_index = chunk_idx,
            ),
        )
```

**BM25 score normalisation:**

BM25 scores are unbounded positive floats. Normalise to `[0.0, 1.0]` using min-max scaling across the result set before constructing `RetrievedChunk` instances:

```python
def _normalise_bm25(score: float, max_score: float) -> float:
    """Scale a single BM25 score relative to the batch maximum."""
    if max_score == 0.0:
        return 0.0
    return min(score / max_score, 1.0)
```

The `_to_chunk` conversion is called after extracting `max_score = response["hits"]["max_score"] or 1.0` from the response envelope.

**Updated `search()` with normalisation:**

```python
async def search(self, query: str, source_id: str, top_k: int = 20) -> list[RetrievedChunk]:
    response  = await self._client.search(index=self.INDEX, body=self._build_query(query, source_id, top_k))
    max_score = response["hits"].get("max_score") or 1.0
    return [
        self._to_chunk(hit, source_id, max_score)
        for hit in response["hits"]["hits"]
    ]
```

**Environment variables:**

```
OPENSEARCH_URL=https://<cluster>.opensearch.amazonaws.com
OPENSEARCH_USERNAME=<secret>
OPENSEARCH_PASSWORD=<secret>
OPENSEARCH_INDEX_NAME=contextiq_chunks
```

**Connection management:**
- `AsyncOpenSearch` is constructed once at startup and injected via FastAPI dependency
- Connection pooling is handled by `opensearch-py`'s default transport layer
- TLS verification enabled in production; `verify_certs=True` is the default and must not be overridden

## Acceptance Criteria

- [ ] `OpenSearchSearchClient.search()` returns a `list[RetrievedChunk]` ordered by descending BM25 score
- [ ] `search_mode` is `"keyword"` for all chunks returned by this client
- [ ] Results are filtered to `source_id` via OpenSearch `filter` clause — no cross-source leakage
- [ ] BM25 scores are normalised to `[0.0, 1.0]` relative to `max_score` in the response
- [ ] `score = 0.0` when `max_score` is zero or absent (empty result set guard)
- [ ] Client is tested against a mocked `AsyncOpenSearch` — no live OpenSearch connection in CI

## Dependencies

- TASK-US012-01 (`RetrievedChunk`, `ChunkMetadata`, `make_chunk_id()`)
- EP-DATA-001 (OpenSearch infrastructure and `contextiq_chunks` index mapping)
- TR-015 (OpenSearch technology spec)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for `src/retrieval/clients/opensearch_client.py`
- [ ] `AsyncOpenSearch` constructed once at app startup — not per search call
- [ ] `verify_certs=True` enforced — no TLS bypass in any environment config
- [ ] `mypy --strict` passes; no `ruff` lint errors
