"""Tests for connector fetch() span decorator — AC-3, AC-4 (TASK-US038-05)."""

from __future__ import annotations

import uuid

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.observability.tracing.connector_span import connector_span
from src.observability.tracing.root_span import start_root_span


class _FakeConnector:
    connector_id: str = "confluence-prod"
    source_id: str = "src-abc123"
    connector_type: str = "confluence"
    _otel_ctx = None
    _request_id: str = ""

    @connector_span
    async def fetch(self, query: str) -> list[dict]:
        return [{"text": "result"}]


async def test_connector_span_created(span_exporter: InMemorySpanExporter):
    """AC-3: fetch() call creates a child span named connector.{connector_id}.fetch."""
    req_id = uuid.uuid4()
    connector = _FakeConnector()

    with start_root_span(req_id) as rsc:
        connector._otel_ctx = rsc
        connector._request_id = str(req_id)
        await connector.fetch("test query")

    span_names = [s.name for s in span_exporter.get_finished_spans()]
    assert "connector.confluence-prod.fetch" in span_names


async def test_connector_span_has_required_attributes(span_exporter: InMemorySpanExporter):
    """AC-4: connector span has connector_id and source_id attributes."""
    req_id = uuid.uuid4()
    connector = _FakeConnector()

    with start_root_span(req_id) as rsc:
        connector._otel_ctx = rsc
        await connector.fetch("test")

    conn_span = next(
        s for s in span_exporter.get_finished_spans()
        if "connector" in s.name
    )
    assert conn_span.attributes.get("connector_id") == "confluence-prod"
    assert conn_span.attributes.get("source_id") == "src-abc123"


async def test_connector_span_no_otel_ctx_does_not_raise(span_exporter: InMemorySpanExporter):
    """AC-3: connector without _otel_ctx runs without instrumentation — no error."""
    connector = _FakeConnector()
    connector._otel_ctx = None
    result = await connector.fetch("test")
    assert result == [{"text": "result"}]
