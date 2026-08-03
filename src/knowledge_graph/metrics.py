"""Prometheus metrics for Knowledge Graph entity extraction — TASK-US028-04.

These metrics satisfy AC-5 (SLA tracking) for the entity extraction pipeline.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

entity_extraction_duration_ms = Histogram(
    "knowledge_graph_entity_extraction_duration_ms",
    "Wall-clock time for a single chunk entity extraction call",
    ["model_id"],
    buckets=[50, 100, 200, 300, 500, 750, 1000, 2000],
)

entity_extraction_total = Counter(
    "knowledge_graph_entity_extraction_total",
    "Total entity extraction attempts",
    ["status"],  # status: "success" | "retried" | "dead_lettered"
)

entities_extracted_total = Counter(
    "knowledge_graph_entities_extracted_total",
    "Total entities written to Neo4j",
    ["entity_type"],
)
