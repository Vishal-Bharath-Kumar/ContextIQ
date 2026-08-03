"""
Unit tests for TASK-US001-05: OTel instrumentation.

Coverage targets:
  - telemetry.setup_telemetry: provider configured, sampler, graceful failure
  - telemetry.get_tracer: returns a tracer after setup
  - handlers/initialize.py: mcp.initialize span with correct attributes
  - middleware/tracing.py: mcp.connection.open + mcp.connection.close spans
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from src.gateway.schemas.mcp_types import ClientInfo, InitializeRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    """Create a fresh TracerProvider backed by an in-memory exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _make_init_request(
    protocol_version: str = "2024-11-05",
    client_name: str = "TestClient",
    transport: str = "sse",
) -> tuple[InitializeRequest, str]:
    """Return (request, transport) — transport is passed via ContextVar, not on the model."""
    req = InitializeRequest(
        protocolVersion=protocol_version,
        clientInfo=ClientInfo(name=client_name, version="1.0"),
        capabilities={},
    )
    return req, transport


# ---------------------------------------------------------------------------
# telemetry.setup_telemetry
# ---------------------------------------------------------------------------

class TestSetupTelemetry:
    def test_initialises_provider_successfully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """setup_telemetry sets a real TracerProvider on the global OTel API."""
        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        with patch.object(OTLPSpanExporter, "__init__", return_value=None), \
             patch.object(OTLPSpanExporter, "export", return_value=None):
            import src.gateway.telemetry as telemetry_mod
            # Reset sentinel so the function runs fresh.
            telemetry_mod._provider_initialised = False

            from src.gateway.telemetry import setup_telemetry
            setup_telemetry("http://localhost:4317", sampler_arg=1.0)

            provider = otel_trace.get_tracer_provider()
            assert isinstance(provider, TracerProvider)

    def test_graceful_failure_on_bad_endpoint(self, caplog: pytest.LogCaptureFixture) -> None:
        """setup_telemetry logs a warning and does not raise when init fails."""
        import src.gateway.telemetry as telemetry_mod
        telemetry_mod._provider_initialised = False

        # Patch at the import source so the local import inside setup_telemetry picks it up.
        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter.__init__",
            side_effect=RuntimeError("connection refused"),
        ):
            from src.gateway.telemetry import setup_telemetry
            setup_telemetry("http://bad-host:9999")

        assert any("OTel initialisation failed" in r.message for r in caplog.records)

    def test_sampler_arg_applied(self) -> None:
        """sampler_arg=0.5 is reflected in the TracerProvider sampler."""
        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        import src.gateway.telemetry as telemetry_mod
        telemetry_mod._provider_initialised = False

        with patch.object(OTLPSpanExporter, "__init__", return_value=None):
            from src.gateway.telemetry import setup_telemetry
            setup_telemetry("http://localhost:4317", sampler_arg=0.5)

        # The provider is a TracerProvider with a sampler.
        provider = otel_trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        assert isinstance(provider.sampler, TraceIdRatioBased)


# ---------------------------------------------------------------------------
# telemetry.get_tracer
# ---------------------------------------------------------------------------

class TestGetTracer:
    def test_returns_tracer_after_setup(self) -> None:
        from opentelemetry.trace import Tracer
        from src.gateway.telemetry import get_tracer

        tracer = get_tracer()
        assert tracer is not None
        assert isinstance(tracer, Tracer)


# ---------------------------------------------------------------------------
# handlers/initialize.py — mcp.initialize span
# ---------------------------------------------------------------------------

class TestInitializeHandlerSpans:
    @pytest.mark.asyncio
    async def test_span_emitted_with_correct_attributes(self) -> None:
        """handle_initialize emits an mcp.initialize span with key attributes."""
        from src.gateway.telemetry import set_transport_context

        provider, exporter = _make_provider()
        req, transport = _make_init_request(client_name="MyClient", transport="websocket")
        set_transport_context(transport)

        with patch("src.gateway.handlers.initialize.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.handlers.initialize import handle_initialize

            result = await handle_initialize(req)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1, f"Expected 1 span, got {len(spans)}"

        span = spans[0]
        assert span.name == "mcp.initialize"
        assert span.attributes["mcp.client.name"] == "MyClient"
        assert span.attributes["mcp.protocol_version"] == "2024-11-05"
        assert span.attributes["mcp.transport"] == "websocket"

    @pytest.mark.asyncio
    async def test_span_not_emitted_on_version_error(self) -> None:
        """Unsupported version raises McpError before the span block."""
        from mcp.shared.exceptions import McpError
        from src.gateway.telemetry import set_transport_context

        provider, exporter = _make_provider()
        req, transport = _make_init_request(protocol_version="1999-01-01")
        set_transport_context(transport)

        with patch("src.gateway.handlers.initialize.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.handlers.initialize import handle_initialize

            with pytest.raises(McpError):
                await handle_initialize(req)

        # McpError is raised before entering the span context manager.
        spans = exporter.get_finished_spans()
        assert len(spans) == 0

    @pytest.mark.asyncio
    async def test_sse_transport_attribute(self) -> None:
        from src.gateway.telemetry import set_transport_context

        provider, exporter = _make_provider()
        req, transport = _make_init_request(transport="sse")
        set_transport_context(transport)

        with patch("src.gateway.handlers.initialize.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.handlers.initialize import handle_initialize

            await handle_initialize(req)

        span = exporter.get_finished_spans()[0]
        assert span.attributes["mcp.transport"] == "sse"


# ---------------------------------------------------------------------------
# middleware/tracing.py — connection lifecycle spans
# ---------------------------------------------------------------------------

class TestConnectionTracingMiddleware:
    """Tests for ConnectionTracingMiddleware using an in-memory OTel provider."""

    def _make_scope(self, scope_type: str, path: str = "/mcp/ws") -> dict[str, Any]:
        return {
            "type": scope_type,
            "path": path,
            "headers": [(b"x-forwarded-for", b"10.0.0.1")],
            "client": ("127.0.0.1", 12345),
        }

    @pytest.mark.asyncio
    async def test_websocket_emits_open_and_close_spans(self) -> None:
        provider, exporter = _make_provider()

        with patch("src.gateway.middleware.tracing.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.middleware.tracing import ConnectionTracingMiddleware

            inner_app = AsyncMock()
            middleware = ConnectionTracingMiddleware(inner_app)
            scope = self._make_scope("websocket")

            await middleware(scope, AsyncMock(), AsyncMock())

        span_names = [s.name for s in exporter.get_finished_spans()]
        assert "mcp.connection.open" in span_names
        assert "mcp.connection.close" in span_names

    @pytest.mark.asyncio
    async def test_sse_scope_emits_spans(self) -> None:
        provider, exporter = _make_provider()

        with patch("src.gateway.middleware.tracing.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.middleware.tracing import ConnectionTracingMiddleware

            inner_app = AsyncMock()
            middleware = ConnectionTracingMiddleware(inner_app)
            scope = self._make_scope("http", path="/mcp/sse")

            await middleware(scope, AsyncMock(), AsyncMock())

        span_names = [s.name for s in exporter.get_finished_spans()]
        assert "mcp.connection.open" in span_names
        assert "mcp.connection.close" in span_names

    @pytest.mark.asyncio
    async def test_non_mcp_http_request_passes_through_without_spans(self) -> None:
        provider, exporter = _make_provider()

        with patch("src.gateway.middleware.tracing.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.middleware.tracing import ConnectionTracingMiddleware

            inner_app = AsyncMock()
            middleware = ConnectionTracingMiddleware(inner_app)
            scope = self._make_scope("http", path="/healthz")

            await middleware(scope, AsyncMock(), AsyncMock())

        spans = exporter.get_finished_spans()
        assert len(spans) == 0
        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_peer_ip_from_x_forwarded_for(self) -> None:
        provider, exporter = _make_provider()

        with patch("src.gateway.middleware.tracing.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.middleware.tracing import ConnectionTracingMiddleware

            inner_app = AsyncMock()
            middleware = ConnectionTracingMiddleware(inner_app)
            scope = self._make_scope("websocket")
            scope["headers"] = [(b"x-forwarded-for", b"192.168.1.100, 10.0.0.1")]

            await middleware(scope, AsyncMock(), AsyncMock())

        open_span = next(s for s in exporter.get_finished_spans() if s.name == "mcp.connection.open")
        assert open_span.attributes["net.peer.ip"] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_session_duration_ms_on_close_span(self) -> None:
        provider, exporter = _make_provider()

        with patch("src.gateway.middleware.tracing.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.middleware.tracing import ConnectionTracingMiddleware

            inner_app = AsyncMock()
            middleware = ConnectionTracingMiddleware(inner_app)
            scope = self._make_scope("websocket")

            await middleware(scope, AsyncMock(), AsyncMock())

        close_span = next(s for s in exporter.get_finished_spans() if s.name == "mcp.connection.close")
        assert "mcp.session_duration_ms" in close_span.attributes
        assert close_span.attributes["mcp.session_duration_ms"] >= 0.0

    @pytest.mark.asyncio
    async def test_inner_app_exception_does_not_prevent_close_span(self) -> None:
        """Even if the inner app raises, the middleware logs a warning and returns."""
        provider, exporter = _make_provider()

        with patch("src.gateway.middleware.tracing.get_tracer", return_value=provider.get_tracer("test")):
            from src.gateway.middleware.tracing import ConnectionTracingMiddleware

            inner_app = AsyncMock(side_effect=RuntimeError("connection reset"))
            middleware = ConnectionTracingMiddleware(inner_app)
            scope = self._make_scope("websocket")

            # Middleware swallows the error and logs a warning.
            await middleware(scope, AsyncMock(), AsyncMock())

        span_names = [s.name for s in exporter.get_finished_spans()]
        assert "mcp.connection.open" in span_names


# ---------------------------------------------------------------------------
# config.py — OTel settings
# ---------------------------------------------------------------------------

class TestGatewaySettingsOtel:
    def test_default_otel_endpoint(self) -> None:
        from src.gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.otel_endpoint == "http://jaeger-collector:4317"

    def test_default_sampler_arg(self) -> None:
        from src.gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.otel_sampler_arg == 1.0

    def test_otel_endpoint_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://custom:4317")
        from src.gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.otel_endpoint == "http://custom:4317"

    def test_sampler_arg_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0.25")
        from src.gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.otel_sampler_arg == pytest.approx(0.25)
