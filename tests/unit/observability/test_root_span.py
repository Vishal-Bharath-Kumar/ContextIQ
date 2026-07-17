"""Unit tests for TASK-US038-02: start_root_span() and _uuid_to_trace_id().

Coverage:
  - _uuid_to_trace_id: deterministic mapping from UUID → 128-bit int (AC-1)
  - start_root_span: trace_id in emitted span equals request_id.hex (AC-1)
  - start_root_span: span attributes request_id and otel.trace_id are set
  - RootSpanContext.trace_id_hex is propagated into AgentState fields
  - Context token is detached after the context manager exits (no leak)
"""
from __future__ import annotations

import uuid

import pytest
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.observability.tracing.root_span import RootSpanContext, _uuid_to_trace_id, start_root_span

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_KNOWN_UUID = uuid.UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6")
_KNOWN_TRACE_ID_INT = 0x3FA85F6457174562B3FC2C963F66AFA6


@pytest.fixture()
def in_memory_provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    """Return a TracerProvider backed by an InMemorySpanExporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.fixture(autouse=True)
def patch_tracer(
    in_memory_provider: tuple[TracerProvider, InMemorySpanExporter],
    monkeypatch: pytest.MonkeyPatch,
) -> TracerProvider:
    """Replace the module-level _TRACER with one from the in-memory provider."""
    provider, _ = in_memory_provider
    import src.observability.tracing.root_span as root_span_mod

    monkeypatch.setattr(
        root_span_mod,
        "_TRACER",
        provider.get_tracer(__name__),
    )
    return provider


# ---------------------------------------------------------------------------
# _uuid_to_trace_id
# ---------------------------------------------------------------------------


class TestUuidToTraceId:
    def test_known_value(self) -> None:
        """AC-1: UUID hex without hyphens == trace ID (128-bit int)."""
        result = _uuid_to_trace_id(_KNOWN_UUID)
        assert result == _KNOWN_TRACE_ID_INT

    def test_zero_uuid(self) -> None:
        zero = uuid.UUID(int=0)
        assert _uuid_to_trace_id(zero) == 0

    def test_max_uuid(self) -> None:
        max_val = uuid.UUID(int=(2**128) - 1)
        assert _uuid_to_trace_id(max_val) == (2**128) - 1

    def test_roundtrip_random(self) -> None:
        uid = uuid.uuid4()
        assert _uuid_to_trace_id(uid) == int(uid.hex, 16)


# ---------------------------------------------------------------------------
# start_root_span
# ---------------------------------------------------------------------------


class TestStartRootSpan:
    def test_trace_id_equals_request_id_hex(
        self, in_memory_provider: tuple[TracerProvider, InMemorySpanExporter]
    ) -> None:
        """AC-1: Root span trace_id in emitted span == request_id.hex."""
        _, exporter = in_memory_provider
        req_id = _KNOWN_UUID

        with start_root_span(req_id) as rsc:
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]

        expected_trace_id = _KNOWN_TRACE_ID_INT
        assert span.context.trace_id == expected_trace_id
        assert rsc.trace_id_hex == _KNOWN_UUID.hex

    def test_span_attributes_set(
        self, in_memory_provider: tuple[TracerProvider, InMemorySpanExporter]
    ) -> None:
        """Root span has request_id and otel.trace_id attributes."""
        _, exporter = in_memory_provider
        req_id = uuid.uuid4()

        with start_root_span(req_id, operation="mcp.test"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = spans[0].attributes
        assert attrs["request_id"] == str(req_id)
        assert attrs["otel.trace_id"] == req_id.hex

    def test_span_kind_is_server(
        self, in_memory_provider: tuple[TracerProvider, InMemorySpanExporter]
    ) -> None:
        _, exporter = in_memory_provider
        with start_root_span(uuid.uuid4()):
            pass
        assert exporter.get_finished_spans()[0].kind == trace.SpanKind.SERVER

    def test_root_span_context_yields_rsc(self) -> None:
        """RootSpanContext is yielded with matching trace_id_hex."""
        req_id = _KNOWN_UUID
        with start_root_span(req_id) as rsc:
            assert isinstance(rsc, RootSpanContext)
            assert rsc.trace_id_hex == req_id.hex
            assert rsc.span is not None
            assert rsc.token is not None

    def test_context_detached_after_exit(self) -> None:
        """OTel context token is detached after the context manager exits."""
        req_id = uuid.uuid4()

        ctx_before = otel_context.get_current()

        with start_root_span(req_id) as _rsc:
            ctx_inside = otel_context.get_current()
            assert ctx_inside is not ctx_before

        # After detach, the active span should not be the root span anymore.
        active_span_after = trace.get_current_span()
        assert not active_span_after.get_span_context().is_valid or \
               active_span_after.get_span_context().trace_id != _uuid_to_trace_id(req_id)

    def test_agent_state_fields_populated(self) -> None:
        """otel_trace_id and _otel_ctx can be stored in a plain dict (AgentState sim)."""
        req_id = uuid.uuid4()
        state: dict = {}

        with start_root_span(req_id) as rsc:
            state["_otel_ctx"] = rsc
            state["otel_trace_id"] = rsc.trace_id_hex

        assert state["otel_trace_id"] == req_id.hex
        assert isinstance(state["_otel_ctx"], RootSpanContext)

    def test_custom_operation_name(
        self, in_memory_provider: tuple[TracerProvider, InMemorySpanExporter]
    ) -> None:
        _, exporter = in_memory_provider
        with start_root_span(uuid.uuid4(), operation="mcp.custom_op"):
            pass
        span = exporter.get_finished_spans()[0]
        assert span.name == "mcp.custom_op"
