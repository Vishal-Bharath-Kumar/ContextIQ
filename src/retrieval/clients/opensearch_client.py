"""OpenSearchSearchClient — async BM25 keyword search against an OpenSearch index.

TASK-US012-03: Executes a BM25 full-text keyword search and returns an ordered
list of ``RetrievedChunk`` instances filtered to the requested ``source_id``.
BM25 scores are normalised to ``[0.0, 1.0]`` relative to the batch maximum
reported by OpenSearch.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from opensearchpy import AsyncOpenSearch

from src.retrieval.schemas.retrieved_chunk import (
    ChunkMetadata,
    RetrievedChunk,
    make_chunk_id,
)


def _normalise_bm25(score: float, max_score: float) -> float:
    """Scale a single BM25 score relative to the batch maximum.

    Returns ``0.0`` when *max_score* is zero to guard against division by zero
    on empty result sets or degenerate responses.
    """
    if max_score == 0.0:
        return 0.0
    return min(score / max_score, 1.0)


class OpenSearchSearchClient:
    """Async BM25 keyword search client backed by OpenSearch.

    The ``AsyncOpenSearch`` client must be constructed once at application
    startup and injected — never created per-request.

    ``INDEX`` is resolved from the ``OPENSEARCH_INDEX_NAME`` environment
    variable at class definition time, defaulting to ``"contextiq_chunks"``.
    """

    INDEX: str = os.getenv("OPENSEARCH_INDEX_NAME", "contextiq_chunks")

    def __init__(self, client: AsyncOpenSearch) -> None:
        self._client = client

    async def search(
        self,
        query: str,
        source_id: str,
        top_k: int = 20,
    ) -> list[RetrievedChunk]:
        """Execute a BM25 keyword search and return the top-*k* results.

        Results are filtered to *source_id*, ordered by descending BM25 score,
        and normalised to ``[0.0, 1.0]`` relative to the batch maximum.
        """
        response = await self._client.search(
            index=self.INDEX,
            body=self._build_query(query, source_id, top_k),
        )
        raw_max = response["hits"].get("max_score")
        max_score = 1.0 if raw_max is None else float(raw_max)
        return [
            self._to_chunk(hit, source_id, max_score)
            for hit in response["hits"]["hits"]
        ]

    @staticmethod
    def _build_query(query: str, source_id: str, top_k: int) -> dict[str, Any]:
        return {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["content^2", "metadata.file_path"],
                                "type": "best_fields",
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
    def _to_chunk(hit: dict[str, Any], source_id: str, max_score: float) -> RetrievedChunk:
        src = hit["_source"]
        meta = src.get("metadata", {})
        chunk_idx = int(meta.get("chunk_index", 0))
        raw_score = float(hit.get("_score", 0.0))

        raw_ts = meta.get("timestamp")
        if raw_ts is None:
            timestamp = datetime.now(UTC)
        elif isinstance(raw_ts, datetime):
            timestamp = raw_ts
        else:
            timestamp = datetime.fromisoformat(str(raw_ts))

        return RetrievedChunk(
            chunk_id=make_chunk_id(source_id, meta.get("file_path", ""), chunk_idx),
            source_id=source_id,
            content=src.get("content", ""),
            score=_normalise_bm25(raw_score, max_score),
            search_mode="keyword",
            metadata=ChunkMetadata(
                file_path=meta.get("file_path", ""),
                timestamp=timestamp,
                author=meta.get("author", ""),
                url=meta.get("url"),
                chunk_index=chunk_idx,
            ),
        )
