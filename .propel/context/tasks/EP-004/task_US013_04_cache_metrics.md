# TASK-US013-04 — Prometheus `context_cache_hit_ratio` Metric

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US013-04 |
| User Story | US-013 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Observability |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Instrument `CachedHybridSearchEngine` with Prometheus counters for cache hits and misses, and derive a `context_cache_hit_ratio` gauge that Grafana can display. Add a scrape-ready `/metrics` assertion to the CI smoke test so the metric is verified present after deployment.

## Implementation Details

**Technology:** Python 3.11+, `prometheus-client>=0.20`

**File locations:**
- `src/retrieval/cache/metrics.py` — metric declarations
- `src/retrieval/engine/cached_hybrid_search.py` — instrumentation (extends TASK-US013-03)
- `tests/retrieval/cache/test_cache_metrics.py`

**Metric declarations:**

```python
# src/retrieval/cache/metrics.py
from prometheus_client import Counter, Gauge

context_cache_requests_total = Counter(
    "context_cache_requests_total",
    "Total cache probe attempts by source and outcome",
    labelnames=["source_id", "result"],   # result = "hit" | "miss"
)

context_cache_hit_ratio = Gauge(
    "context_cache_hit_ratio",
    "Rolling cache hit ratio across all sources (updated on every probe)",
)
```

**Instrumentation in `CachedHybridSearchEngine.search()`:**

```python
# src/retrieval/engine/cached_hybrid_search.py  (extends TASK-US013-03)
from src.retrieval.cache.metrics import context_cache_requests_total, context_cache_hit_ratio

class CachedHybridSearchEngine:
    # Running totals maintained in-process for ratio calculation
    _hits:   int = 0
    _misses: int = 0

    async def search(self, ...) -> tuple[list[RetrievedChunk], bool]:
        query_vector = self._embedder.embed(query)
        cache_key    = make_cache_key(source_id, query_vector, token_budget)
        cached       = await self._cache.get(cache_key)

        if cached is not None:
            context_cache_requests_total.labels(source_id=source_id, result="hit").inc()
            CachedHybridSearchEngine._hits += 1
            self._update_ratio()
            return cached, True

        chunks = await self._engine.search(query, source_id, ranking_strategy)
        if chunks:
            await self._cache.set(cache_key, chunks)

        context_cache_requests_total.labels(source_id=source_id, result="miss").inc()
        CachedHybridSearchEngine._misses += 1
        self._update_ratio()
        return chunks, False

    @classmethod
    def _update_ratio(cls) -> None:
        total = cls._hits + cls._misses
        if total > 0:
            context_cache_hit_ratio.set(cls._hits / total)
```

**Ratio calculation note:**
- In-process counters reset on pod restart; the Prometheus metric reflects the rolling ratio for the lifetime of the current process
- Grafana should apply a `rate()` or `increase()` over `context_cache_requests_total` for cross-pod aggregate ratios; the `context_cache_hit_ratio` gauge is a per-pod convenience for quick debugging

**`/metrics` endpoint:**
The FastAPI gateway already exposes `/metrics` via `prometheus-client`'s ASGI middleware (added with EP-001). No new endpoint is needed — the new counters and gauge appear automatically on the next scrape.

**Grafana panel spec:**
```
Panel: Context Cache Hit Ratio
Query: avg(context_cache_hit_ratio)
Thresholds: < 0.5 → red, 0.5–0.8 → yellow, > 0.8 → green
```

## Acceptance Criteria

- [ ] `context_cache_requests_total{source_id="github", result="hit"}` increments on cache hits
- [ ] `context_cache_requests_total{source_id="github", result="miss"}` increments on cache misses
- [ ] `context_cache_hit_ratio` equals `hits / (hits + misses)` after N requests
- [ ] `context_cache_hit_ratio` is `0.0` when no requests have been processed (initial state)
- [ ] Both metrics are present in the `/metrics` scrape output
- [ ] Unit tests assert counter and gauge values without a live Prometheus server (using `prometheus_client` default registry)

## Dependencies

- TASK-US013-03 (`CachedHybridSearchEngine.search()` — instrumented here)
- TASK-US001-05 (OTel and Prometheus middleware already mounted on FastAPI gateway)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Metric declarations are module-level singletons — not instantiated per request
- [ ] Unit tests cover: hit increments, miss increments, ratio after mixed hits/misses, zero-request initial state
- [ ] `mypy --strict` passes; no `ruff` lint errors
