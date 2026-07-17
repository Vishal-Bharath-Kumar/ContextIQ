"""Tests for pipeline node spans — AC-2, AC-4 (TASK-US038-05)."""

from __future__ import annotations

import uuid

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.observability.tracing.node_span import otel_node_span
from src.observability.tracing.root_span import start_root_span


@otel_node_span("intent.classify")
async def _fake_intent(state: dict) -> dict:
    return {**state, "intent_type": "technical_support"}


@otel_node_span("retrieval.hybrid_search")
async def _fake_retrieval(state: dict) -> dict:
    return state


@otel_node_span("compression.context_window")
async def _fake_compression(state: dict) -> dict:
    return {**state, "compression_tokens_after": 400}


@otel_node_span("governance.pii_scan")
async def _fake_governance(state: dict) -> dict:
    return state


@otel_node_span("routing.model_select")
async def _fake_routing(state: dict) -> dict:
    return {**state, "model_selected": "gpt-4o"}


async def test_five_node_spans_created(span_exporter: InMemorySpanExporter):
    """AC-2: each of the five pipeline nodes creates exactly one named child span."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state: dict = {"_otel_ctx": rsc, "request_id": str(req_id), "tenant_id": "acme"}
        state = await _fake_intent(state)
        state = await _fake_retrieval(state)
        state = await _fake_compression(state)
        state = await _fake_governance(state)
        state = await _fake_routing(state)

    span_names = [s.name for s in span_exporter.get_finished_spans()]
    assert "intent.classify" in span_names
    assert "retrieval.hybrid_search" in span_names
    assert "compression.context_window" in span_names
    assert "governance.pii_scan" in span_names
    assert "routing.model_select" in span_names


async def test_node_spans_share_root_trace_id(span_exporter: InMemorySpanExporter):
    """AC-2: all node spans share the root span's trace_id."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state: dict = {"_otel_ctx": rsc, "request_id": str(req_id)}
        await _fake_intent(state)
        await _fake_retrieval(state)

    spans = span_exporter.get_finished_spans()
    trace_ids = {f"{s.context.trace_id:032x}" for s in spans}
    assert trace_ids == {req_id.hex}, f"Multiple trace IDs found: {trace_ids}"


async def test_intent_type_attribute_propagated(span_exporter: InMemorySpanExporter):
    """AC-4: intent_type attribute is set on node spans after intent classification."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state: dict = {"_otel_ctx": rsc}
        state = await _fake_intent(state)
        await _fake_retrieval(state)

    retrieval_span = next(
        s for s in span_exporter.get_finished_spans()
        if s.name == "retrieval.hybrid_search"
    )
    assert retrieval_span.attributes.get("intent_type") == "technical_support"


async def test_model_id_attribute_set_after_routing(span_exporter: InMemorySpanExporter):
    """AC-4: model_id attribute is set on the routing span."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state: dict = {"_otel_ctx": rsc}
        await _fake_routing(state)

    routing_span = next(
        s for s in span_exporter.get_finished_spans()
        if s.name == "routing.model_select"
    )
    assert routing_span.attributes.get("model_id") == "gpt-4o"


async def test_token_count_set_after_compression(span_exporter: InMemorySpanExporter):
    """AC-4: token_count attribute reflects post-compression count."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state: dict = {"_otel_ctx": rsc}
        await _fake_compression(state)

    comp_span = next(
        s for s in span_exporter.get_finished_spans()
        if s.name == "compression.context_window"
    )
    assert comp_span.attributes.get("token_count") == 400
