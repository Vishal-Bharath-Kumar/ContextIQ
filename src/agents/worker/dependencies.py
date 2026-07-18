"""Dependency injection helpers for the agent worker service.

TASK-US013-03: Provides singleton accessors for CachedHybridSearchEngine,
wiring together HybridSearchEngine (TASK-US012-05) and ContextCacheStore
(TASK-US013-02) via lru_cache so that a single instance is reused across
all requests without per-request construction.

Usage
-----
Call ``get_cached_hybrid_search_engine()`` from ``retrieval_node``
(or any FastAPI route that needs it).  The underlying singletons
(``get_hybrid_search_engine()``, ``get_context_cache_store()``) must be
seeded via their respective ``set_*`` functions at application startup.
"""

from __future__ import annotations

from functools import lru_cache

from src.retrieval.cache.cache_store import ContextCacheStore
from src.retrieval.engine.cached_hybrid_search import CachedHybridSearchEngine
from src.retrieval.engine.hybrid_search import get_hybrid_search_engine

# ---------------------------------------------------------------------------
# ContextCacheStore singleton — seeded at startup via set_context_cache_store()
# ---------------------------------------------------------------------------

_cache_store: ContextCacheStore | None = None


def set_context_cache_store(store: ContextCacheStore) -> None:
    """Inject the ``ContextCacheStore`` singleton.

    Must be called once during application startup (FastAPI lifespan) before
    the first agent request.  In tests, call this in a fixture with a mock
    instance.  Clears the ``lru_cache`` on ``get_cached_hybrid_search_engine``
    so the next call rebuilds with the new store.
    """
    global _cache_store  # noqa: PLW0603
    _cache_store = store
    get_cached_hybrid_search_engine.cache_clear()


def get_context_cache_store() -> ContextCacheStore:
    """Return the active ``ContextCacheStore`` singleton.

    Raises:
        RuntimeError: when ``set_context_cache_store()`` has not been called.
    """
    if _cache_store is None:
        raise RuntimeError(
            "ContextCacheStore has not been initialised. "
            "Call set_context_cache_store() during application startup."
        )
    return _cache_store


# ---------------------------------------------------------------------------
# CachedHybridSearchEngine singleton — built lazily from the two above
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_cached_hybrid_search_engine() -> CachedHybridSearchEngine:
    """Return a lazily-constructed ``CachedHybridSearchEngine`` singleton.

    Delegates to the module-level singletons for ``HybridSearchEngine`` and
    ``ContextCacheStore``.  Both must have been seeded before the first call.

    Returns:
        The shared :class:`~src.retrieval.engine.cached_hybrid_search.CachedHybridSearchEngine`
        instance.

    Raises:
        RuntimeError: when either the ``HybridSearchEngine`` or
            ``ContextCacheStore`` singleton has not been initialised.
    """
    return CachedHybridSearchEngine(
        engine=get_hybrid_search_engine(),
        cache=get_context_cache_store(),
    )
