"""Prometheus metrics for the knowledge graph updater pipeline — TASK-US030-04.

These metrics satisfy AC-4 (throughput tracking) and AC-5/AC-6 (batch observability)
for the graph update pipeline.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

graph_update_batch_duration_seconds = Histogram(
    "knowledge_graph_update_batch_duration_seconds",
    "Wall-clock duration to process one sync batch (source.synced event)",
    ["source_type"],
    buckets=[0.5, 1, 2, 3, 5, 10, 30],
)

graph_relationships_upserted_total = Counter(
    "knowledge_graph_relationships_upserted_total",
    "Cumulative relationships written to Neo4j",
    ["edge_type"],
)

graph_relationships_expired_total = Counter(
    "knowledge_graph_relationships_expired_total",
    "Cumulative stale relationships removed",
)

graph_tombstone_deletions_total = Counter(
    "knowledge_graph_tombstone_deletions_total",
    "Relationships removed by tombstone events",
)
