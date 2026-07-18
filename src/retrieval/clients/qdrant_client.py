"""QdrantSearchClient — async ANN vector search against a Qdrant collection.

TASK-US012-02: Embeds the query using the configured embedding model, executes
an Approximate Nearest Neighbour (ANN) search, and returns an ordered list of
``RetrievedChunk`` instances filtered to the requested ``source_id``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, ScoredPoint

from src.retrieval.embedding.embedder import QueryEmbedder
from src.retrieval.schemas.retrieved_chunk import (
    ChunkMetadata,
    RetrievedChunk,
    make_chunk_id,
)


class QdrantSearchClient:
    """Async ANN vector search client backed by Qdrant.

    The ``AsyncQdrantClient`` must be constructed once at application startup
    and injected — never created per-request.

    ``COLLECTION`` is resolved from the ``QDRANT_COLLECTION_NAME`` environment
    variable at class definition time, defaulting to ``"contextiq_chunks"``.
    """

    COLLECTION: str = os.getenv("QDRANT_COLLECTION_NAME", "contextiq_chunks")
    VECTOR_SIZE: int = 384  # BAAI/bge-small-en-v1.5 dimensionality

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client
        self._embedder = QueryEmbedder.get()

    async def search(
        self,
        query: str,
        source_id: str,
        top_k: int = 20,
    ) -> list[RetrievedChunk]:
        """Embed *query* and return the top-*k* ANN results for *source_id*.

        Results are ordered by descending score (highest relevance first).
        """
        query_vector = self._embedder.embed(query)

        hits: list[ScoredPoint] = await self._client.search(
            collection_name=self.COLLECTION,
            query_vector=query_vector,
            query_filter=self._source_filter(source_id),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        return [self._to_chunk(hit, source_id) for hit in hits]

    @staticmethod
    def _source_filter(source_id: str) -> Filter:
        return Filter(
            must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
        )

    @staticmethod
    def _to_chunk(hit: ScoredPoint, source_id: str) -> RetrievedChunk:
        payload = hit.payload or {}
        meta = payload.get("metadata", {})
        chunk_idx = int(payload.get("chunk_index", 0))

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
            content=payload.get("content", ""),
            score=min(max(float(hit.score), 0.0), 1.0),
            search_mode="vector",
            metadata=ChunkMetadata(
                file_path=meta.get("file_path", ""),
                timestamp=timestamp,
                author=meta.get("author", ""),
                url=meta.get("url"),
                chunk_index=chunk_idx,
            ),
        )
