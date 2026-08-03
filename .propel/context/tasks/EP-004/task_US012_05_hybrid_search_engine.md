# TASK-US012-05 — `HybridSearchEngine`: Parallel Dispatch, p95 Latency Benchmark, and `AgentState` Storage

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US012-05 |
| User Story | US-012 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend / Performance |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement `HybridSearchEngine`, the orchestrator that fires Qdrant ANN and OpenSearch BM25 searches concurrently via `asyncio.gather`, feeds both result lists into the RRF merger, and writes the final `list[RetrievedChunk]` into `AgentState.raw_context`. Add a CI benchmark that asserts p95 hybrid search latency < 1 s (mocked backends). Wire the engine into the `retrieval_agent` node as the primary search path when `execution_plan.ranking_strategy` is `"semantic"`, `"bm25"`, or `"hybrid"`.

## Implementation Details

**Technology:** Python 3.11+, `asyncio`, `langgraph>=0.2.0`, `pytest-benchmark`

**File locations:**
- `src/retrieval/engine/hybrid_search.py` — `HybridSearchEngine` class
- `src/agents/nodes/retrieval_agent.py` — extended to call `HybridSearchEngine` (extends TASK-US007-01)
- `tests/retrieval/engine/test_hybrid_search.py`
- `tests/retrieval/engine/test_hybrid_search_benchmark.py`

**`HybridSearchEngine`:**

```python
# src/retrieval/engine/hybrid_search.py
import asyncio
from src.retrieval.clients.qdrant_client   import QdrantSearchClient
from src.retrieval.clients.opensearch_client import OpenSearchSearchClient
from src.retrieval.fusion.rrf              import rrf_merge, DEFAULT_TOP_K
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk
from src.agents.schemas.execution_plan     import RankingStrategy

class HybridSearchEngine:
    def __init__(
        self,
        qdrant:      QdrantSearchClient,
        opensearch:  OpenSearchSearchClient,
        top_k:       int = DEFAULT_TOP_K,
    ) -> None:
        self._qdrant     = qdrant
        self._opensearch = opensearch
        self._top_k      = top_k

    async def search(
        self,
        query:            str,
        source_id:        str,
        ranking_strategy: RankingStrategy = RankingStrategy.HYBRID,
    ) -> list[RetrievedChunk]:
        """Execute hybrid search and return RRF-merged top-K chunks."""
        if ranking_strategy == RankingStrategy.BM25:
            return await self._opensearch.search(query, source_id, self._top_k)

        if ranking_strategy == RankingStrategy.SEMANTIC:
            return await self._qdrant.search(query, source_id, self._top_k)

        # HYBRID: both searches run concurrently
        vector_results, keyword_results = await asyncio.gather(
            self._qdrant.search(query, source_id, self._top_k),
            self._opensearch.search(query, source_id, self._top_k),
        )
        return rrf_merge(vector_results, keyword_results, top_k=self._top_k)
```

**Integration into `retrieval_agent` node:**

```python
# src/agents/nodes/retrieval_agent.py  (extends TASK-US007-01, TASK-US010-04)
from src.retrieval.engine.hybrid_search import HybridSearchEngine

async def retrieval_node(state: AgentState) -> dict:
    plan    = state["execution_plan"]
    engine  = get_hybrid_search_engine()   # FastAPI dependency, singleton

    all_chunks: list[RetrievedChunk] = []
    for source_id in plan.sources:
        chunks = await engine.search(
            query            = state["prompt"],
            source_id        = source_id,
            ranking_strategy = plan.ranking_strategy,
        )
        # Enforce per-source token budget (TASK-US010-04)
        budget = plan.token_budget_per_source.get(source_id)
        if budget is not None:
            chunks = truncate_to_budget(chunks, budget)
        all_chunks.extend(chunks)

    return {
        "raw_context":  all_chunks,
        "ranked_context": all_chunks,   # re-ranking applied by governance node (EP-005)
        "current_node": "retrieval_agent",
        "status":       ExecutionStatus.RUNNING,
    }
```

**p95 latency benchmark:**

```python
# tests/retrieval/engine/test_hybrid_search_benchmark.py
import asyncio, pytest
from unittest.mock import AsyncMock
from src.retrieval.engine.hybrid_search import HybridSearchEngine
from src.agents.schemas.execution_plan  import RankingStrategy

MOCK_CHUNKS = [...]   # 20 pre-built RetrievedChunk instances

@pytest.mark.benchmark(max_time=1.0)
def test_hybrid_search_p95_latency(benchmark):
    engine = HybridSearchEngine(
        qdrant     = AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
        opensearch = AsyncMock(search=AsyncMock(return_value=MOCK_CHUNKS)),
    )

    result = benchmark(
        lambda: asyncio.run(
            engine.search("fix authentication bug", "github", RankingStrategy.HYBRID)
        )
    )
    assert len(result) <= 20
```

**Per-source loop vs. single-source dispatch:**
- `retrieval_node` iterates over `plan.sources` and calls `engine.search()` per source sequentially; sources themselves are kept isolated to prevent cross-source RRF pollution
- Multi-source parallelism (calling `engine.search()` for all sources concurrently) is a future optimisation tracked in the performance backlog — sequential is safe and correct for Phase 1

## Acceptance Criteria

- [ ] `HybridSearchEngine.search()` with `HYBRID` strategy dispatches Qdrant and OpenSearch calls via `asyncio.gather` (both calls start before either awaits)
- [ ] `SEMANTIC` strategy calls only Qdrant; `BM25` strategy calls only OpenSearch
- [ ] `retrieval_agent` node populates `AgentState.raw_context` with a `list[RetrievedChunk]`
- [ ] Result list contains at most `top_k` items (default 20) per source
- [ ] CI benchmark passes: mocked `HybridSearchEngine.search()` completes in < 1 s p95
- [ ] `get_hybrid_search_engine()` returns the same singleton instance across requests (no per-request construction)

## Dependencies

- TASK-US012-01 (`RetrievedChunk` — populates `AgentState.raw_context`)
- TASK-US012-02 (`QdrantSearchClient` — injected into engine)
- TASK-US012-03 (`OpenSearchSearchClient` — injected into engine)
- TASK-US012-04 (`rrf_merge()` — called for `HYBRID` strategy)
- TASK-US010-04 (`truncate_to_budget()` — applied per source after search)
- TASK-US010-03 (`execution_plan.ranking_strategy` — drives strategy dispatch)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `HybridSearchEngine` is the single entry point for all retrieval — no direct client calls in `retrieval_agent`
- [ ] Unit tests cover: HYBRID parallel dispatch, SEMANTIC single-path, BM25 single-path, top-K truncation
- [ ] Benchmark test is part of the CI pipeline and fails the build if p95 > 1 000 ms (mocked latency baseline)
- [ ] `mypy --strict` passes; no `ruff` lint errors
