"""
Prometheus metrics for the Connector SDK.

TASK-US021-03: ConnectorHealthPoller — 30-Second Background Health Check.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge

connector_health_checks_total = Counter(
    "connector_health_checks_total",
    "Total health check calls per connector and outcome",
    ["connector_id", "status"],  # status: "healthy" | "unhealthy"
)

connectors_enabled_gauge = Gauge(
    "connectors_enabled_total",
    "Number of connectors currently in enabled state",
)
