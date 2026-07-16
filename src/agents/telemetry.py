"""
OTel tracer factory and Prometheus metrics for the agents pipeline.

TASK-US006-03: Node Entry/Exit Structured Logging with Per-Node Timing.
TASK-US006-05: End-to-End Pipeline SLA Benchmark (p95 < 3 s).

Usage
-----
Import ``node_duration_histogram`` to observe per-node durations, import
``pipeline_e2e_duration`` to record full-pipeline wall-clock time, and call
``get_tracer()`` to obtain the OTel tracer for the ``contextiq.agents``
instrumentation scope.
"""
from __future__ import annotations

from prometheus_client import Histogram

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

node_duration_histogram = Histogram(
    "contextiq_pipeline_node_duration_seconds",
    "Duration of each pipeline node execution",
    ["node_name", "status"],  # status: success | failed
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0],
)

# TASK-US006-05: full-pipeline wall-clock latency, labelled by execution path.
# path values: full | skip_compression | clarification | failed
pipeline_e2e_duration = Histogram(
    "contextiq_pipeline_e2e_duration_seconds",
    "Full pipeline execution time from state init to final_response",
    ["path"],
    buckets=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# OTel tracer factory
# ---------------------------------------------------------------------------

_TRACER_NAME = "contextiq.agents"


def get_tracer() -> object:
    """Return the OTel tracer for the agents pipeline.

    Falls back to a no-op tracer when the OTel SDK is not available or the
    global provider has not been initialised (e.g. in unit tests that do not
    call ``setup_telemetry``).
    """
    try:
        from opentelemetry import trace  # noqa: PLC0415

        return trace.get_tracer(_TRACER_NAME)
    except Exception:  # noqa: BLE001
        return _NoOpTracer()


class _NoOpTracer:
    """Minimal no-op tracer used when the OTel SDK is unavailable."""

    def start_as_current_span(self, *args: object, **kwargs: object) -> object:  # noqa: ANN401
        from contextlib import nullcontext  # noqa: PLC0415

        return nullcontext(self)

    def set_attribute(self, *args: object, **kwargs: object) -> None:
        pass

    def record_exception(self, *args: object, **kwargs: object) -> None:
        pass

    def set_status(self, *args: object, **kwargs: object) -> None:
        pass
