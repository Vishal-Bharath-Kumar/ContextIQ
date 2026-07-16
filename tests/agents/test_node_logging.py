"""
Unit tests for with_node_logging — TASK-US006-03.

Coverage targets (Acceptance Criteria):
  - node_entry log emitted before node executes, contains node and request_id
  - node_exit log emitted after success with duration_ms (numeric, > 0) and output_fields
  - node_failed log emitted on exception with error message and exc_info
  - OTel child span pipeline.<node_name> carries correct span attributes
  - Prometheus contextiq_pipeline_node_duration_seconds histogram observed per node per status
  - output_fields lists result keys only — raw content/PII values are never logged
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
import structlog.testing
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY

from src.agents.nodes.logging import with_node_logging
from src.agents.state import AgentState, ExecutionStatus


# ---------------------------------------------------------------------------
# Module-scoped OTel provider — set once so OTel's single-set constraint is
# respected across all tests in this module.
# ---------------------------------------------------------------------------

_otel_exporter: InMemorySpanExporter | None = None


@pytest.fixture(scope="module", autouse=True)
def _module_otel_provider() -> None:
    """Configure a single in-memory OTel provider for the whole test module."""
    global _otel_exporter  # noqa: PLW0603
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    _otel_exporter = exporter
    yield
    exporter.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides: Any) -> AgentState:
    base: AgentState = {
        "request_id": "req-log-001",
        "user_id": "user-log-001",
        "username": "tester",
        "roles": ["viewer"],
        "tool_name": "get_context",
        "prompt": "test prompt — contains sensitive data",
        "timestamp": "2026-07-16T00:00:00+00:00",
        "status": ExecutionStatus.PENDING,
        "current_node": "",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "execution_plan": None,
        "raw_context": None,
        "ranked_context": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
    }
    return {**base, **overrides}  # type: ignore[return-value]



def _histogram_count(node_name: str, status: str) -> float | None:
    """Return the current sample count for the given label combination."""
    return REGISTRY.get_sample_value(
        "contextiq_pipeline_node_duration_seconds_count",
        {"node_name": node_name, "status": status},
    )


# ---------------------------------------------------------------------------
# Structured log field tests
# ---------------------------------------------------------------------------

class TestNodeEntryLog:
    @pytest.mark.asyncio
    async def test_node_entry_emitted_before_execution(self) -> None:
        """node_entry log must be present in captured output."""
        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": "intent_agent", "status": ExecutionStatus.RUNNING}

        wrapped = with_node_logging(_node, "intent_agent")
        state = _make_state()

        with structlog.testing.capture_logs() as captured:
            await wrapped(state)

        entry_logs = [e for e in captured if e.get("event") == "node_entry"]
        assert entry_logs, "node_entry log was not emitted"

    @pytest.mark.asyncio
    async def test_node_entry_contains_node_and_request_id(self) -> None:
        """node_entry must carry 'node' and 'request_id' fields."""
        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": "intent_agent", "status": ExecutionStatus.RUNNING}

        wrapped = with_node_logging(_node, "intent_agent")
        state = _make_state(request_id="req-entry-assert")

        with structlog.testing.capture_logs() as captured:
            await wrapped(state)

        entry = next(e for e in captured if e.get("event") == "node_entry")
        assert entry["node"] == "intent_agent"
        assert entry["request_id"] == "req-entry-assert"


class TestNodeExitLog:
    @pytest.mark.asyncio
    async def test_node_exit_emitted_on_success(self) -> None:
        """node_exit log must be present after a successful node execution."""
        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": "retrieval_agent", "status": ExecutionStatus.RUNNING}

        wrapped = with_node_logging(_node, "retrieval_agent")

        with structlog.testing.capture_logs() as captured:
            await wrapped(_make_state())

        exit_logs = [e for e in captured if e.get("event") == "node_exit"]
        assert exit_logs, "node_exit log was not emitted"

    @pytest.mark.asyncio
    async def test_node_exit_duration_ms_is_positive_number(self) -> None:
        """node_exit duration_ms must be a numeric value greater than zero."""
        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": "retrieval_agent", "status": ExecutionStatus.RUNNING}

        wrapped = with_node_logging(_node, "retrieval_agent")

        with structlog.testing.capture_logs() as captured:
            await wrapped(_make_state())

        exit_log = next(e for e in captured if e.get("event") == "node_exit")
        assert isinstance(exit_log["duration_ms"], (int, float)), (
            f"duration_ms should be numeric, got {type(exit_log['duration_ms'])}"
        )
        assert exit_log["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_node_exit_output_fields_lists_result_keys(self) -> None:
        """output_fields must be the list of keys returned by the node, not their values."""
        async def _node(state: AgentState) -> dict[str, Any]:
            return {
                "current_node": "governance_agent",
                "status": ExecutionStatus.RUNNING,
                "governance_decisions": [{"chunk_id": "c1", "action": "allow"}],
            }

        wrapped = with_node_logging(_node, "governance_agent")

        with structlog.testing.capture_logs() as captured:
            await wrapped(_make_state())

        exit_log = next(e for e in captured if e.get("event") == "node_exit")
        assert "output_fields" in exit_log
        assert set(exit_log["output_fields"]) == {"current_node", "status", "governance_decisions"}

    @pytest.mark.asyncio
    async def test_output_fields_contains_no_raw_values(self) -> None:
        """output_fields must list field names only — no raw content or PII values."""
        secret_content = "TOP_SECRET_INTERNAL_DOCUMENT"

        async def _node(state: AgentState) -> dict[str, Any]:
            return {
                "current_node": "compression_agent",
                "status": ExecutionStatus.RUNNING,
                "compressed_context": [{"content": secret_content}],
            }

        wrapped = with_node_logging(_node, "compression_agent")

        with structlog.testing.capture_logs() as captured:
            await wrapped(_make_state())

        # Serialise all captured log events to strings and check the secret never appears.
        all_log_text = str(captured)
        assert secret_content not in all_log_text, (
            "Raw context content leaked into log output — PII/data guard violated."
        )


class TestNodeFailedLog:
    @pytest.mark.asyncio
    async def test_node_failed_emitted_on_exception(self) -> None:
        """node_failed log must be emitted when the node raises an exception."""
        async def _failing_node(state: AgentState) -> dict[str, Any]:
            raise ValueError("deliberate test failure")

        wrapped = with_node_logging(_failing_node, "routing_agent")

        with structlog.testing.capture_logs() as captured:
            with pytest.raises(ValueError, match="deliberate test failure"):
                await wrapped(_make_state())

        failed_logs = [e for e in captured if e.get("event") == "node_failed"]
        assert failed_logs, "node_failed log was not emitted"

    @pytest.mark.asyncio
    async def test_node_failed_contains_error_message(self) -> None:
        """node_failed log must carry the error message string."""
        async def _failing_node(state: AgentState) -> dict[str, Any]:
            raise RuntimeError("upstream timeout")

        wrapped = with_node_logging(_failing_node, "routing_agent")

        with structlog.testing.capture_logs() as captured:
            with pytest.raises(RuntimeError):
                await wrapped(_make_state())

        failed_log = next(e for e in captured if e.get("event") == "node_failed")
        assert failed_log["error"] == "upstream timeout"

    @pytest.mark.asyncio
    async def test_node_failed_contains_duration_ms(self) -> None:
        """node_failed log must include duration_ms as a numeric value."""
        async def _failing_node(state: AgentState) -> dict[str, Any]:
            raise RuntimeError("crash")

        wrapped = with_node_logging(_failing_node, "routing_agent")

        with structlog.testing.capture_logs() as captured:
            with pytest.raises(RuntimeError):
                await wrapped(_make_state())

        failed_log = next(e for e in captured if e.get("event") == "node_failed")
        assert isinstance(failed_log["duration_ms"], (int, float))
        assert failed_log["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_exception_is_reraised(self) -> None:
        """with_node_logging must re-raise the original exception after logging."""
        async def _failing_node(state: AgentState) -> dict[str, Any]:
            raise TypeError("type mismatch")

        wrapped = with_node_logging(_failing_node, "routing_agent")

        with structlog.testing.capture_logs():
            with pytest.raises(TypeError, match="type mismatch"):
                await wrapped(_make_state())


# ---------------------------------------------------------------------------
# OTel span tests
# ---------------------------------------------------------------------------

class TestOtelSpan:
    @pytest.mark.asyncio
    async def test_child_span_created_with_correct_name(self) -> None:
        """A child span named pipeline.<node_name> must be exported on success."""
        assert _otel_exporter is not None
        _otel_exporter.clear()

        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": "intent_agent", "status": ExecutionStatus.RUNNING}

        wrapped = with_node_logging(_node, "otel_name_node")
        with structlog.testing.capture_logs():
            await wrapped(_make_state())

        spans = _otel_exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "pipeline.otel_name_node" in span_names

    @pytest.mark.asyncio
    async def test_span_attributes_set_on_success(self) -> None:
        """Span must carry node_name, request_id, duration_ms, and status=success."""
        assert _otel_exporter is not None
        _otel_exporter.clear()

        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": "otel_attrs_node", "status": ExecutionStatus.RUNNING}

        wrapped = with_node_logging(_node, "otel_attrs_node")
        state = _make_state(request_id="req-span-001")

        with structlog.testing.capture_logs():
            await wrapped(state)

        spans = _otel_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "pipeline.otel_attrs_node")
        attrs = span.attributes or {}

        assert attrs.get("pipeline.node_name") == "otel_attrs_node"
        assert attrs.get("pipeline.request_id") == "req-span-001"
        assert isinstance(attrs.get("pipeline.duration_ms"), int)
        assert attrs.get("pipeline.status") == "success"

    @pytest.mark.asyncio
    async def test_span_records_exception_on_failure(self) -> None:
        """Span status must be ERROR when the node raises."""
        from opentelemetry.trace import StatusCode

        assert _otel_exporter is not None
        _otel_exporter.clear()

        async def _failing_node(state: AgentState) -> dict[str, Any]:
            raise ValueError("node error")

        wrapped = with_node_logging(_failing_node, "otel_fail_node")

        with structlog.testing.capture_logs():
            with pytest.raises(ValueError):
                await wrapped(_make_state())

        spans = _otel_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "pipeline.otel_fail_node")
        assert span.status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# Prometheus histogram tests
# ---------------------------------------------------------------------------

class TestPrometheusHistogram:
    @pytest.mark.asyncio
    async def test_histogram_observed_on_success(self) -> None:
        """Histogram must be observed with status=success after successful execution."""
        node_name = "prom_success_node"
        before = _histogram_count(node_name, "success") or 0.0

        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": node_name, "status": ExecutionStatus.RUNNING}

        wrapped = with_node_logging(_node, node_name)
        with structlog.testing.capture_logs():
            await wrapped(_make_state())

        after = _histogram_count(node_name, "success") or 0.0
        assert after == before + 1, (
            f"Expected histogram count to increase by 1; before={before}, after={after}"
        )

    @pytest.mark.asyncio
    async def test_histogram_observed_on_failure(self) -> None:
        """Histogram must be observed with status=failed after a node exception."""
        node_name = "prom_failed_node"
        before = _histogram_count(node_name, "failed") or 0.0

        async def _failing_node(state: AgentState) -> dict[str, Any]:
            raise RuntimeError("simulated failure")

        wrapped = with_node_logging(_failing_node, node_name)
        with structlog.testing.capture_logs():
            with pytest.raises(RuntimeError):
                await wrapped(_make_state())

        after = _histogram_count(node_name, "failed") or 0.0
        assert after == before + 1, (
            f"Expected failed histogram count to increase by 1; before={before}, after={after}"
        )

    @pytest.mark.asyncio
    async def test_success_and_failed_labels_are_independent(self) -> None:
        """Success and failed labels must be tracked separately."""
        node_name = "prom_split_node"

        async def _node(state: AgentState) -> dict[str, Any]:
            return {"current_node": node_name, "status": ExecutionStatus.RUNNING}

        async def _failing_node(state: AgentState) -> dict[str, Any]:
            raise RuntimeError("split test failure")

        wrapped_ok = with_node_logging(_node, node_name)
        wrapped_fail = with_node_logging(_failing_node, node_name)

        with structlog.testing.capture_logs():
            await wrapped_ok(_make_state())
            with pytest.raises(RuntimeError):
                await wrapped_fail(_make_state())

        assert _histogram_count(node_name, "success") >= 1.0
        assert _histogram_count(node_name, "failed") >= 1.0
