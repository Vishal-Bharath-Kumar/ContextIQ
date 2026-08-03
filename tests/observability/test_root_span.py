"""Tests for root span factory — AC-1, AC-7 (TASK-US038-05)."""

from __future__ import annotations

import uuid

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.observability.tracing.root_span import RootSpanContext, _uuid_to_trace_id, start_root_span


def test_uuid_to_trace_id_strips_hyphens():
    """AC-1: UUID maps to its 128-bit integer — same as parsing hex without hyphens."""
    uid = uuid.UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6")
    assert _uuid_to_trace_id(uid) == int("3fa85f6457174562b3fc2c963f66afa6", 16)


def test_root_span_trace_id_equals_request_id_hex(span_exporter: InMemorySpanExporter):
    """AC-1: root span trace_id in hex equals request_id without hyphens."""
    req_id = uuid.uuid4()
    with start_root_span(req_id):
        pass

    spans = span_exporter.get_finished_spans()
    assert len(spans) >= 1

    root = spans[0]
    trace_id_hex = f"{root.context.trace_id:032x}"
    assert trace_id_hex == req_id.hex, (
        f"Expected trace_id {req_id.hex}, got {trace_id_hex}"
    )


def test_root_span_has_request_id_attribute(span_exporter: InMemorySpanExporter):
    """AC-1: root span carries request_id as a span attribute."""
    req_id = uuid.uuid4()
    with start_root_span(req_id, operation="mcp.test"):
        pass

    spans = span_exporter.get_finished_spans()
    attrs = spans[0].attributes
    assert attrs.get("request_id") == str(req_id)


def test_root_span_context_stored_in_rsc(span_exporter: InMemorySpanExporter):
    """AC-1: RootSpanContext.trace_id_hex matches the started span's trace_id."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        assert rsc.trace_id_hex == req_id.hex
