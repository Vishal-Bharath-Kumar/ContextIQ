"""Unit tests for OTel concurrent span instrumentation — TASK-US007-05.

Acceptance criteria verified:
  - connector_spans_are_children:  each connector.fetch.* span has pipeline.retrieval_agent as parent
  - timeout_span_error_status:     timed-out connector span has status=ERROR and connector.timed_out=true
  - chunks_returned_attribute:     connector.chunks_returned attribute present on successful spans
  - span_attributes_set:           connector.source_id, connector.type, connector.token_budget set
  - concurrent_spans_same_parent:  all connector spans share the same parent span_id
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.trace import ProxyTracerProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from src.agents.retrieval.parallel_dispatcher import (
    ConnectorTimeoutError,
    ParallelConnectorDispatcher,
)
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata


# ---------------------------------------------------------------------------
# Module-scoped OTel provider — one provider for the whole module avoids the
# OTel "already set" warning on repeated set_tracer_provider() calls.
# ---------------------------------------------------------------------------

_otel_exporter: InMemorySpanExporter


@pytest.fixture(scope="module", autouse=True)
def _module_otel_provider() -> None:
    global _otel_exporter  # noqa: PLW0603
    exporter = InMemorySpanExporter()
    provider = otel_trace.get_tracer_provider()
    if isinstance(provider, ProxyTracerProvider):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)
    else:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    _otel_exporter = exporter
    yield
    exporter.shutdown()


@pytest.fixture(autouse=True)
def _clear_spans() -> None:
    """Reset exporter before every test so spans don't bleed across tests."""
    _otel_exporter.clear()
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FETCHED_AT = datetime(2026, 7, 16, tzinfo=UTC)


def _make_result(source_id: str = "item-1", content: str = "hello") -> ConnectorResult:
    return ConnectorResult(
        source_id=source_id,
        content=content,
        metadata=ResultMetadata(source_url="https://example.com"),
        fetched_at=_FETCHED_AT,
    )


def _fast_connector(source_id: str = "item-1") -> MagicMock:
    connector = MagicMock()
    connector.fetch = AsyncMock(return_value=[_make_result(source_id)])
    return connector


def _slow_connector(delay: float = 10.0) -> MagicMock:
    async def _slow_fetch(_query: ConnectorQuery) -> list[ConnectorResult]:
        await asyncio.sleep(delay)
        return []  # pragma: no cover

    connector = MagicMock()
    connector.fetch = AsyncMock(side_effect=_slow_fetch)
    return connector


def _make_registry(source_map: dict) -> MagicMock:
    registry = MagicMock()
    registry.get.side_effect = lambda src: source_map.get(src)
    return registry


def _run_under_retrieval_span(coro: object) -> list:
    """Run *coro* under a pipeline.retrieval_agent parent span and return finished spans."""
    tracer = otel_trace.get_tracer("contextiq.test")

    async def _wrapper() -> None:
        with tracer.start_as_current_span("pipeline.retrieval_agent"):
            await coro

    asyncio.get_event_loop().run_until_complete(_wrapper())
    return _otel_exporter.get_finished_spans()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConnectorSpansAreChildrenOfRetrievalAgent:
    @pytest.mark.asyncio
    async def test_connector_spans_are_children_of_retrieval_agent_span(self) -> None:
        """Each connector.fetch.* span must be a child of pipeline.retrieval_agent."""
        registry = _make_registry(
            {
                "github:org/repo": _fast_connector(),
                "confluence:wiki": _fast_connector(),
            }
        )
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="what is auth?",
                    source_ids=["github:org/repo", "confluence:wiki"],
                    token_budget_per_source={},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        retrieval_span = next(
            (s for s in spans if s.name == "pipeline.retrieval_agent"), None
        )
        connector_spans = [s for s in spans if s.name.startswith("connector.fetch.")]

        assert retrieval_span is not None, "pipeline.retrieval_agent span not found"
        assert len(connector_spans) == 2, f"Expected 2 connector spans, got {len(connector_spans)}"

        for cs in connector_spans:
            assert cs.parent is not None, f"Span {cs.name} has no parent"
            assert cs.parent.span_id == retrieval_span.context.span_id, (
                f"Span {cs.name} parent {cs.parent.span_id!r} != "
                f"retrieval span {retrieval_span.context.span_id!r}"
            )

    @pytest.mark.asyncio
    async def test_all_connector_spans_share_same_parent(self) -> None:
        """Four concurrent connector spans must all share the same parent span_id."""
        registry = _make_registry(
            {
                "github:org": _fast_connector(),
                "confluence:space": _fast_connector(),
                "jira:project": _fast_connector(),
                "grafana:dashboard": _fast_connector(),
            }
        )
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="deployment metrics",
                    source_ids=["github:org", "confluence:space", "jira:project", "grafana:dashboard"],
                    token_budget_per_source={},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        retrieval_span = next(s for s in spans if s.name == "pipeline.retrieval_agent")
        connector_spans = [s for s in spans if s.name.startswith("connector.fetch.")]

        assert len(connector_spans) == 4
        parent_ids = {cs.parent.span_id for cs in connector_spans}
        assert parent_ids == {retrieval_span.context.span_id}, (
            "All connector spans must share the retrieval_agent span as parent"
        )


class TestConnectorSpanAttributes:
    @pytest.mark.asyncio
    async def test_span_attributes_set_on_success(self) -> None:
        """connector.source_id, connector.type, connector.token_budget must be set."""
        registry = _make_registry({"github:org/repo": _fast_connector()})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="test",
                    source_ids=["github:org/repo"],
                    token_budget_per_source={"github:org/repo": 500},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        connector_span = next(s for s in spans if s.name.startswith("connector.fetch."))
        attrs = connector_span.attributes

        assert attrs["connector.source_id"] == "github:org/repo"
        assert attrs["connector.type"] == "github"
        assert attrs["connector.token_budget"] == 500

    @pytest.mark.asyncio
    async def test_chunks_returned_attribute_on_success(self) -> None:
        """connector.chunks_returned must be present and correct on successful spans."""
        connector = MagicMock()
        connector.fetch = AsyncMock(
            return_value=[_make_result("r1", "chunk one"), _make_result("r2", "chunk two")]
        )
        registry = _make_registry({"confluence:wiki": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="test",
                    source_ids=["confluence:wiki"],
                    token_budget_per_source={},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        connector_span = next(s for s in spans if s.name.startswith("connector.fetch."))

        assert connector_span.attributes["connector.chunks_returned"] == 2
        assert connector_span.status.status_code == StatusCode.OK

    @pytest.mark.asyncio
    async def test_duration_ms_attribute_positive(self) -> None:
        """connector.duration_ms must be a non-negative integer."""
        registry = _make_registry({"jira:board": _fast_connector()})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="test",
                    source_ids=["jira:board"],
                    token_budget_per_source={},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        connector_span = next(s for s in spans if s.name.startswith("connector.fetch."))
        assert connector_span.attributes["connector.duration_ms"] >= 0


class TestTimeoutSpan:
    @pytest.mark.asyncio
    async def test_timed_out_connector_span_has_error_status(self) -> None:
        """A timed-out connector must produce a span with status=ERROR."""
        registry = _make_registry({"grafana:slow": _slow_connector(delay=10.0)})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=0.05)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="test",
                    source_ids=["grafana:slow"],
                    token_budget_per_source={},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        connector_span = next(s for s in spans if s.name.startswith("connector.fetch."))

        assert connector_span.status.status_code == StatusCode.ERROR
        assert connector_span.attributes.get("connector.timed_out") is True

    @pytest.mark.asyncio
    async def test_timed_out_span_is_child_of_retrieval_agent(self) -> None:
        """Even a timed-out connector span must be parented to pipeline.retrieval_agent."""
        registry = _make_registry({"grafana:slow": _slow_connector(delay=10.0)})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=0.05)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="test",
                    source_ids=["grafana:slow"],
                    token_budget_per_source={},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        retrieval_span = next(s for s in spans if s.name == "pipeline.retrieval_agent")
        connector_span = next(s for s in spans if s.name.startswith("connector.fetch."))

        assert connector_span.parent is not None
        assert connector_span.parent.span_id == retrieval_span.context.span_id

    @pytest.mark.asyncio
    async def test_generic_error_span_records_exception(self) -> None:
        """A connector raising a generic exception must have span.record_exception called."""
        err = ValueError("connection refused")
        error_connector = MagicMock()
        error_connector.fetch = AsyncMock(side_effect=err)
        registry = _make_registry({"confluence:broken": error_connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)
        tracer = otel_trace.get_tracer("contextiq.test")

        async def _run() -> None:
            with tracer.start_as_current_span("pipeline.retrieval_agent"):
                await dispatcher.fetch_all(
                    query="test",
                    source_ids=["confluence:broken"],
                    token_budget_per_source={},
                )

        await _run()

        spans = _otel_exporter.get_finished_spans()
        connector_span = next(s for s in spans if s.name.startswith("connector.fetch."))

        assert connector_span.status.status_code == StatusCode.ERROR
        # Span should have at least one recorded event from record_exception
        assert any(e.name == "exception" for e in connector_span.events)
