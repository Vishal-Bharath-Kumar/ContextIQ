"""HybridSearchEngine — parallel Qdrant ANN + OpenSearch BM25 dispatch.

TASK-US012-05: Orchestrates concurrent vector and keyword search, feeds both
result lists into the RRF merger, and returns a unified ``list[RetrievedChunk]``.

Singleton lifecycle
-------------------
``set_hybrid_search_engine()`` must be called once at application startup
(FastAPI lifespan) before the first agent request is processed.  Tests call it
directly with a mock instance.  ``get_hybrid_search_engine()`` returns the
same instance for every request — no per-request construction.
"""

from __future__ import annotations

import asyncio

from src.agents.schemas.execution_plan import RankingStrategy
from src.retrieval.clients.opensearch_client import OpenSearchSearchClient
from src.retrieval.clients.qdrant_client import QdrantSearchClient
from src.retrieval.fusion.rrf import DEFAULT_TOP_K, rrf_merge
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


class HybridSearchEngine:
    """Orchestrate parallel vector and keyword search with RRF fusion.

    Dispatch strategy is driven by ``RankingStrategy``:

    - ``SEMANTIC``: Qdrant ANN only.
    - ``BM25``:     OpenSearch BM25 only.
    - ``HYBRID``:   Both searches run concurrently via :func:`asyncio.gather`;
                    results are merged with :func:`~src.retrieval.fusion.rrf.rrf_merge`.
    """

    def __init__(
        self,
        qdrant: QdrantSearchClient,
        opensearch: OpenSearchSearchClient,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self._qdrant = qdrant
        self._opensearch = opensearch
        self._top_k = top_k

    async def search(
        self,
        query: str,
        source_id: str,
        ranking_strategy: RankingStrategy = RankingStrategy.HYBRID,
    ) -> list[RetrievedChunk]:
        """Execute search and return at most ``top_k`` RRF-merged chunks.

        Args:
            query:            Raw user query string.
            source_id:        Connector/store identifier to filter results.
            ranking_strategy: Controls which backends are queried.

        Returns:
            Ordered ``list[RetrievedChunk]`` with at most ``top_k`` items.
        """
        if ranking_strategy == RankingStrategy.BM25:
            return await self._opensearch.search(query, source_id, self._top_k)

        if ranking_strategy == RankingStrategy.SEMANTIC:
            return await self._qdrant.search(query, source_id, self._top_k)

        # HYBRID: both searches start concurrently — neither awaits before the other.
        vector_results, keyword_results = await asyncio.gather(
            self._qdrant.search(query, source_id, self._top_k),
            self._opensearch.search(query, source_id, self._top_k),
        )
        return rrf_merge(vector_results, keyword_results, top_k=self._top_k)


# ---------------------------------------------------------------------------
# Module-level singleton — set once at startup, reused across all requests
# ---------------------------------------------------------------------------

_engine: HybridSearchEngine | None = None


def set_hybrid_search_engine(engine: HybridSearchEngine) -> None:
    """Inject the ``HybridSearchEngine`` singleton.

    Must be called once during application startup (FastAPI lifespan) before
    the first agent request.  In tests, call this in a fixture with a mock
    instance.
    """
    global _engine  # noqa: PLW0603
    _engine = engine


def get_hybrid_search_engine() -> HybridSearchEngine:
    """Return the active ``HybridSearchEngine`` singleton.

    Raises:
        RuntimeError: when ``set_hybrid_search_engine()`` has not been called.
    """
    if _engine is None:
        raise RuntimeError(
            "HybridSearchEngine has not been initialised. "
            "Call set_hybrid_search_engine() during application startup."
        )
    return _engine
