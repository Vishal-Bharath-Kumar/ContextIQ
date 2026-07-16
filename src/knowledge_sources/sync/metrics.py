"""Prometheus metrics for knowledge source sync operations — TASK-US026-02.

AC-7: record sync duration and document count delta per connector type.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

sync_duration_seconds = Histogram(
    "knowledge_source_sync_duration_seconds",
    "Duration of a completed knowledge source sync job",
    ["connector_type", "status"],  # status: "succeeded" | "failed"
    buckets=[1, 5, 15, 30, 60, 120, 300],
)

sync_document_count_delta = Counter(
    "knowledge_source_sync_documents_total",
    "Cumulative documents processed across all sync jobs",
    ["connector_type"],
)

sync_retries_total = Counter(
    "knowledge_source_sync_retries_total",
    "Number of sync retry attempts",
    ["connector_type"],
)
