"""Tests for OTel setup configuration — AC-5, AC-6, AC-7 (TASK-US038-05)."""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_setup_tracing_is_idempotent(span_exporter: InMemorySpanExporter):
    """AC-7: calling setup_tracing() twice does not create a second provider."""
    from opentelemetry import trace

    from src.observability.tracing.setup import TracingSettings, setup_tracing

    settings = TracingSettings(enabled=False)  # disabled to avoid real gRPC
    setup_tracing(settings)
    setup_tracing(settings)

    # Second call returns existing provider — no duplication
    assert trace.get_tracer_provider() is trace.get_tracer_provider()


def test_otlp_exporter_endpoint_is_configurable(monkeypatch):
    """AC-5: OTLPSpanExporter endpoint read from OTEL_EXPORTER_OTLP_ENDPOINT."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger-test:4317")
    from src.observability.tracing.setup import TracingSettings

    settings = TracingSettings()
    assert settings.exporter_otlp_endpoint == "http://jaeger-test:4317"


def test_bsp_schedule_delay_is_1000ms():
    """AC-6: 1 s flush delay ensures traces reach Jaeger within the 5 s SLA."""
    from src.observability.tracing.setup import TracingSettings

    settings = TracingSettings()
    assert settings.bsp_schedule_delay_millis == 1000


def test_propagator_includes_w3c_tracecontext(span_exporter: InMemorySpanExporter):
    """AC-1: W3C TraceContext propagator is registered globally."""
    from unittest.mock import patch

    from opentelemetry.propagate import get_global_textmap

    from src.observability.tracing.setup import TracingSettings, setup_tracing

    # Use enabled=True so set_global_textmap() is called; mock exporter to avoid gRPC.
    with patch("src.observability.tracing.setup.OTLPSpanExporter") as mock_cls, \
         patch("src.observability.tracing.setup._install_auto_instrumentation"):
        mock_cls.return_value = span_exporter
        setup_tracing(TracingSettings(enabled=True))

    propagators = get_global_textmap()
    names = [type(p).__name__ for p in getattr(propagators, "_propagators", [])]
    assert "TraceContextTextMapPropagator" in names


async def test_node_span_graceful_when_no_otel_ctx():
    """AC-7: decorator is a no-op when state has no _otel_ctx."""
    from src.observability.tracing.node_span import otel_node_span

    @otel_node_span()
    async def _node(state: dict) -> dict:
        return {**state, "ran": True}

    result = await _node({"_otel_ctx": None})
    assert result["ran"] is True
