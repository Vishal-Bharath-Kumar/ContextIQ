"""Prometheus metrics for connector dispatch — TASK-US007-02 / TASK-US008-04.

Single source of truth for all connector-related Prometheus metrics.

Exposes:

* ``contextiq_connector_failure_count`` — unified failure counter labelled by
  *connector_id* and *failure_type* (``timeout`` | ``error`` | ``circuit_open``).
  Replaces the previous ``connector_timeouts_total``, ``connector_errors_total``,
  and ``connector_circuit_skip_total`` counters from TASK-US007-02.
* ``contextiq_connector_circuit_breaker_state`` — gauge per connector encoding
  circuit-breaker state (0=closed, 1=open, 2=half_open).
* ``contextiq_connector_fetch_duration_seconds`` — histogram of per-connector
  fetch latency labelled by *connector_id* and *status* (``success`` |
  ``timeout`` | ``error``).
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# --- Failure counter (AC-4) ---
# failure_type: timeout | error | circuit_open
connector_failure_count = Counter(
    "contextiq_connector_failure_count",
    "Total connector fetch failures (timeout + errors + circuit open skips)",
    ["connector_id", "failure_type"],
)

# --- Circuit-breaker state gauge (AC-5/6) ---
connector_circuit_breaker_state = Gauge(
    "contextiq_connector_circuit_breaker_state",
    "Circuit breaker state per connector (0=closed, 1=open, 2=half_open)",
    ["connector_id"],
)

# --- Fetch duration histogram ---
connector_fetch_duration = Histogram(
    "contextiq_connector_fetch_duration_seconds",
    "Per-connector fetch duration in seconds",
    ["connector_id", "status"],  # status: success | timeout | error
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0],
)
