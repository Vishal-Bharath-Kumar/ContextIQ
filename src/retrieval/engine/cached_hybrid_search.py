"""Cache-aside decorator for HybridSearchEngine.

TASK-US013-03: CachedHybridSearchEngine wraps HybridSearchEngine with a
Redis-backed cache probe.  On a hit the stored chunks are returned immediately
(target < 50 ms); on a miss the full hybrid search executes and the result is
written to cache before returning.

Design notes
------------
- Cache logic is entirely isolated here — HybridSearchEngine and retrieval_agent
  remain unaware of caching.
- Empty results are never written to cache to prevent transient connector
  failures (e.g. Qdrant timeout) from poisoning subsequent requests.
- The returned bool flag lets callers (retrieval_node) skip redundant
  token-budget truncation on cache-hit chunks, which were already truncated
  at write time.

Singleton lifecycle
-------------------
``set_cached_hybrid_search_engine()`` must be called once at application
startup (FastAPI lifespan) before the first agent request is processed.
Tests call it directly with a mock instance.
``get_cached_hybrid_search_engine()`` returns the same instance for every
request — no per-request construction.
"""

from __future__ import annotations

from src.agents.schemas.execution_plan import RankingStrategy
from src.retrieval.cache.cache_key import make_cache_key
from src.retrieval.cache.cache_store import ContextCacheStore
from src.retrieval.cache.metrics import context_cache_hit_ratio, context_cache_requests_total
from src.retrieval.embedding.embedder import QueryEmbedder
from src.retrieval.engine.hybrid_search import HybridSearchEngine
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


class CachedHybridSearchEngine:
    """Cache-aside wrapper around :class:`HybridSearchEngine`.

    Each :meth:`search` call first probes the Redis cache via
    :class:`~src.retrieval.cache.cache_store.ContextCacheStore`.  On a hit the
    cached chunks are returned immediately without touching Qdrant or
    OpenSearch.  On a miss the underlying engine executes the full search and
    the result (if non-empty) is written back to cache.
    """

    # Running totals maintained in-process for ratio calculation.
    # Reset on pod restart — see module docstring for cross-pod strategy.
    _hits: int = 0
    _misses: int = 0

    def __init__(
        self,
        engine: HybridSearchEngine,
        cache: ContextCacheStore,
        embedder: QueryEmbedder | None = None,
    ) -> None:
        self._engine = engine
        self._cache = cache
        self._embedder = embedder if embedder is not None else QueryEmbedder.get()

    async def search(
        self,
        query: str,
        source_id: str,
        token_budget: int,
        ranking_strategy: RankingStrategy = RankingStrategy.HYBRID,
    ) -> tuple[list[RetrievedChunk], bool]:
        """Search with cache-aside.

        Args:
            query:            Raw user query string.
            source_id:        Connector/store identifier to filter results.
            token_budget:     Token quota allocated to this source; included in
                              cache key so different budgets get distinct entries.
            ranking_strategy: Forwarded to the underlying engine on a cache miss.

        Returns:
            A ``(chunks, cache_hit)`` tuple.  ``cache_hit`` is ``True`` when
            the result was served from cache without executing the hybrid search.
        """
        query_vector = self._embedder.embed(query)
        cache_key = make_cache_key(source_id, query_vector, token_budget)

        # Cache probe — fast path
        cached = await self._cache.get(cache_key)
        if cached is not None:
            context_cache_requests_total.labels(source_id=source_id, result="hit").inc()
            CachedHybridSearchEngine._hits += 1
            self._update_ratio()
            return cached, True

        # Cache miss — execute full hybrid search
        chunks = await self._engine.search(query, source_id, ranking_strategy)

        # Write to cache only on non-empty result (guard against transient failures)
        if chunks:
            await self._cache.set(cache_key, chunks)

        context_cache_requests_total.labels(source_id=source_id, result="miss").inc()
        CachedHybridSearchEngine._misses += 1
        self._update_ratio()
        return chunks, False

    @classmethod
    def _update_ratio(cls) -> None:
        """Recompute and set the ``context_cache_hit_ratio`` gauge."""
        total = cls._hits + cls._misses
        if total > 0:
            context_cache_hit_ratio.set(cls._hits / total)


# ---------------------------------------------------------------------------
# Module-level singleton — set once at startup, reused across all requests
# ---------------------------------------------------------------------------

_cached_engine: CachedHybridSearchEngine | None = None


def set_cached_hybrid_search_engine(engine: CachedHybridSearchEngine) -> None:
    """Inject the ``CachedHybridSearchEngine`` singleton.

    Must be called once during application startup (FastAPI lifespan) before
    the first agent request.  In tests, call this in a fixture with a mock
    instance.
    """
    global _cached_engine  # noqa: PLW0603
    _cached_engine = engine


def get_cached_hybrid_search_engine() -> CachedHybridSearchEngine:
    """Return the active ``CachedHybridSearchEngine`` singleton.

    Raises:
        RuntimeError: when ``set_cached_hybrid_search_engine()`` has not been
            called.
    """
    if _cached_engine is None:
        raise RuntimeError(
            "CachedHybridSearchEngine has not been initialised. "
            "Call set_cached_hybrid_search_engine() during application startup."
        )
    return _cached_engine
