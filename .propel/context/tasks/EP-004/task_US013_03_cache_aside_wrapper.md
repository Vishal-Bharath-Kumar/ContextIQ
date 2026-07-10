# TASK-US013-03 — Cache-Aside Wrapper for `HybridSearchEngine`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US013-03 |
| User Story | US-013 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `CachedHybridSearchEngine`, the cache-aside decorator that wraps `HybridSearchEngine`. On each search call it checks the cache first; on a hit it returns the stored chunks immediately (< 50 ms), on a miss it executes the full hybrid search and writes the result to cache before returning. This keeps all cache logic out of the core engine (TASK-US012-05) and out of `retrieval_agent`.

## Implementation Details

**Technology:** Python 3.11+

**File locations:**
- `src/retrieval/engine/cached_hybrid_search.py` — `CachedHybridSearchEngine` class
- `src/agents/nodes/retrieval_agent.py` — swap `HybridSearchEngine` → `CachedHybridSearchEngine` (extends TASK-US012-05)
- `tests/retrieval/engine/test_cached_hybrid_search.py`

**`CachedHybridSearchEngine`:**

```python
# src/retrieval/engine/cached_hybrid_search.py
from src.retrieval.engine.hybrid_search    import HybridSearchEngine
from src.retrieval.cache.cache_store       import ContextCacheStore
from src.retrieval.cache.cache_key         import make_cache_key, ContextCacheKey
from src.retrieval.embedding.embedder      import QueryEmbedder
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk
from src.agents.schemas.execution_plan     import RankingStrategy

class CachedHybridSearchEngine:
    def __init__(
        self,
        engine:   HybridSearchEngine,
        cache:    ContextCacheStore,
        embedder: QueryEmbedder | None = None,
    ) -> None:
        self._engine   = engine
        self._cache    = cache
        self._embedder = embedder or QueryEmbedder.get()

    async def search(
        self,
        query:            str,
        source_id:        str,
        token_budget:     int,
        ranking_strategy: RankingStrategy = RankingStrategy.HYBRID,
    ) -> tuple[list[RetrievedChunk], bool]:
        """Search with cache-aside.

        Returns: (chunks, cache_hit)
        """
        query_vector = self._embedder.embed(query)
        cache_key    = make_cache_key(source_id, query_vector, token_budget)

        # Cache probe
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached, True

        # Cache miss — execute full hybrid search
        chunks = await self._engine.search(query, source_id, ranking_strategy)

        # Write to cache only on non-empty result (avoid caching transient failures)
        if chunks:
            await self._cache.set(cache_key, chunks)

        return chunks, False
```

**Integration into `retrieval_agent` node:**

```python
# src/agents/nodes/retrieval_agent.py  (replace HybridSearchEngine reference — TASK-US012-05)
from src.retrieval.engine.cached_hybrid_search import CachedHybridSearchEngine

async def retrieval_node(state: AgentState) -> dict:
    plan   = state["execution_plan"]
    engine = get_cached_hybrid_search_engine()    # singleton via FastAPI dependency

    all_chunks: list[RetrievedChunk] = []
    for source_id in plan.sources:
        budget = plan.token_budget_per_source.get(source_id, plan.token_budget_total)
        chunks, cache_hit = await engine.search(
            query            = state["prompt"],
            source_id        = source_id,
            token_budget     = budget,
            ranking_strategy = plan.ranking_strategy,
        )
        if not cache_hit:
            chunks = truncate_to_budget(chunks, budget)   # only truncate on live results
        all_chunks.extend(chunks)

    return {
        "raw_context":    all_chunks,
        "ranked_context": all_chunks,
        "current_node":   "retrieval_agent",
        "status":         ExecutionStatus.RUNNING,
    }
```

**Cache-hit truncation note:** Cached chunks have already been truncated to `token_budget` at write time — re-truncating on retrieval is redundant and must be skipped to preserve the original ordering.

**Empty-result policy:** An empty chunk list from the hybrid search is not written to cache. This prevents a transient connector failure (e.g. Qdrant timeout) from poisoning the cache and causing subsequent requests to receive empty results for the TTL duration.

**Singleton wiring:**

```python
# src/agents/worker/dependencies.py
from functools import lru_cache

@lru_cache(maxsize=1)
def get_cached_hybrid_search_engine() -> CachedHybridSearchEngine:
    return CachedHybridSearchEngine(
        engine   = get_hybrid_search_engine(),   # from TASK-US012-05
        cache    = get_context_cache_store(),    # ContextCacheStore singleton
    )
```

## Acceptance Criteria

- [ ] `CachedHybridSearchEngine.search()` returns `(chunks, True)` when a cache hit occurs
- [ ] `CachedHybridSearchEngine.search()` returns `(chunks, False)` and writes to cache on a miss
- [ ] Cache is not written when `chunks` is empty (transient failure guard)
- [ ] On a cache hit, `HybridSearchEngine.search()` is NOT called (asserted via mock call count)
- [ ] On a cache miss, `ContextCacheStore.set()` is called exactly once with the result
- [ ] `retrieval_agent` node skips `truncate_to_budget` on cache-hit chunks

## Dependencies

- TASK-US013-01 (`make_cache_key()`)
- TASK-US013-02 (`ContextCacheStore.get()`, `set()`)
- TASK-US012-05 (`HybridSearchEngine.search()` — wrapped, not replaced)
- TASK-US012-02 (`QueryEmbedder.get()` — embedding needed for key derivation)
- TASK-US010-04 (`truncate_to_budget()` — applied only on live search results)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `retrieval_agent` no longer imports `HybridSearchEngine` directly — only `CachedHybridSearchEngine`
- [ ] Unit tests cover: cache hit, cache miss + write, empty-result no-write, truncation skip on hit
- [ ] `mypy --strict` passes; no `ruff` lint errors
