"""Prometheus metric declarations for the context retrieval cache.

TASK-US013-04: Counters and gauge for cache hit/miss tracking.

Metrics
-------
context_cache_requests_total
    Counter labelled by (source_id, result) where result is "hit" or "miss".
    Monotonically increasing — survives pod restarts only if a remote
    push-gateway is used.  Prefer ``rate()``/``increase()`` in Grafana for
    cross-pod aggregate ratios.

context_cache_hit_ratio
    Per-process rolling gauge set on every cache probe.  Useful for quick
    per-pod debugging in Grafana without PromQL aggregation.

Both metrics are module-level singletons and are registered with the default
``prometheus_client`` registry exactly once at import time.  Do NOT
instantiate them inside request handlers.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

context_cache_requests_total = Counter(
    "context_cache_requests_total",
    "Total cache probe attempts by source and outcome",
    labelnames=["source_id", "result"],  # result = "hit" | "miss"
)

context_cache_hit_ratio = Gauge(
    "context_cache_hit_ratio",
    "Rolling cache hit ratio across all sources (updated on every probe)",
)
