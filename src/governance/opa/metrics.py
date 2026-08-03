"""Prometheus metrics for OPA policy evaluation — TASK-US032-04 (AC-7)."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# AC-7: required metric name.
governance_policy_denials_total = Counter(
    "governance_policy_denials_total",
    "Number of context chunks denied by OPA policy evaluation",
    ["tenant_id", "classification_label"],
)

opa_evaluation_duration_ms = Histogram(
    "governance_opa_evaluation_duration_ms",
    "Per-chunk OPA evaluation latency",
    ["result"],  # result: "allow" | "deny"
    buckets=[1, 5, 10, 20, 30, 50, 75, 100],
)
