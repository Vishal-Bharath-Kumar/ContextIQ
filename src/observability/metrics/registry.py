from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# AC-2 + AC-3: all four metrics with all four required label dimensions.
_LABEL_NAMES = ["service", "endpoint", "intent_type", "tenant_id"]

contextiq_requests_total = Counter(
    "contextiq_requests_total",
    "Total number of HTTP requests handled.",
    _LABEL_NAMES,
)

contextiq_request_duration_seconds = Histogram(
    "contextiq_request_duration_seconds",
    "HTTP request latency in seconds.",
    _LABEL_NAMES,
    # Buckets tuned for ContextIQ latency profile; p95 alert threshold is 3 s
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
)

contextiq_errors_total = Counter(
    "contextiq_errors_total",
    "Total number of requests that resulted in a 5xx error.",
    _LABEL_NAMES,
)

contextiq_active_requests = Gauge(
    "contextiq_active_requests",
    "Number of requests currently being processed.",
    _LABEL_NAMES,
)
