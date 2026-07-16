"""Unit tests for TASK-US006-04: Pipeline Failure Handling.

Coverage targets (Acceptance Criteria):
  - with_error_handling: exception → structured failed-state dict with correct JSON fields
  - with_error_handling: no exception → result passed through unchanged
  - Each of the 5 pipeline node names produces correct ``failed_node`` in error JSON
  - ``pipeline_failed`` terminal node returns ``status=FAILED`` and ``current_node="pipeline_failed"``
  - NodeWrapper.wrap composition: with_error_handling is innermost (exception never propagates)
  - Retrieval failure skips compression_agent and routing_agent (verified via mock call-count)
  - POST /v1/execute returns HTTP 200 with status="error" (not 500) when final_state is FAILED
  - AgentState.error contains valid JSON with required fields: failed_node, error_type, message, timestamp
  - Prometheus histogram records status="failed" when with_error_handling catches an exception
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from src.agent_worker.routers.execute import router, set_graph
from src.agent_worker.schemas.execute_types import ExecuteRequest, ExecuteResponse, ToolCallError
from src.agents.graph import build_graph
from src.agents.nodes.base import NodeWrapper, with_error_handling
from src.agents.nodes.pipeline_failed import failed_terminal_node
from src.agents.state import AgentState, ExecutionStatus
from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PIPELINE_NODES = [
    "intent_agent",
    "retrieval_agent",
    "governance_agent",
    "compression_agent",
    "routing_agent",
]

_SAMPLE_EXECUTE_REQUEST = {
    "request_id": "req-fail-001",
    "user_id": "user-fail-001",
    "username": "tester",
    "roles": ["developer"],
    "tool_name": "context_search",
    "arguments": {"prompt": "test prompt"},
    "trace_id": "a" * 32,
}


def _make_state(**overrides: Any) -> AgentState:
    base: AgentState = {
        "request_id": "req-fail-test",
        "user_id": "user-fail-test",
        "username": "tester",
        "roles": ["viewer"],
        "tool_name": "get_context",
        "prompt": "what is the pipeline?",
        "timestamp": "2026-07-16T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "intent_agent",
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


def _histogram_count(node_name: str, status: str) -> float:
    val = REGISTRY.get_sample_value(
        "contextiq_pipeline_node_duration_seconds_count",
        {"node_name": node_name, "status": status},
    )
    return val or 0.0


# ---------------------------------------------------------------------------
# with_error_handling — unit tests
# ---------------------------------------------------------------------------


class TestWithErrorHandling:
    @pytest.mark.asyncio
    async def test_exception_returns_failed_state_dict(self) -> None:
        """Any exception must be caught and returned as a failed-state dict."""
        async def _failing(state: AgentState) -> dict:
            raise RuntimeError("qdrant connection refused")

        wrapped = with_error_handling(_failing, "intent_agent")
        result = await wrapped(_make_state())

        assert result["status"] == ExecutionStatus.FAILED
        assert result["current_node"] == "intent_agent"

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self) -> None:
        """with_error_handling must never re-raise — the wrapper always returns."""
        async def _failing(state: AgentState) -> dict:
            raise ValueError("unexpected error")

        wrapped = with_error_handling(_failing, "retrieval_agent")
        # If it raises, the test fails — no pytest.raises needed.
        result = await wrapped(_make_state())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_success_passes_through_unchanged(self) -> None:
        """When no exception is raised the original return dict must be passed through."""
        expected = {"status": ExecutionStatus.RUNNING, "current_node": "intent_agent"}

        async def _ok(state: AgentState) -> dict:
            return expected

        wrapped = with_error_handling(_ok, "intent_agent")
        result = await wrapped(_make_state())
        assert result is expected

    @pytest.mark.asyncio
    async def test_error_field_is_valid_json(self) -> None:
        """The ``error`` field must be a JSON-serialisable string."""
        async def _failing(state: AgentState) -> dict:
            raise ConnectionRefusedError("Connection refused to Qdrant")

        wrapped = with_error_handling(_failing, "retrieval_agent")
        result = await wrapped(_make_state())

        assert isinstance(result["error"], str)
        payload = json.loads(result["error"])
        assert isinstance(payload, dict)

    @pytest.mark.asyncio
    async def test_error_payload_contains_required_fields(self) -> None:
        """Error JSON must contain failed_node, error_type, message, and timestamp."""
        async def _failing(state: AgentState) -> dict:
            raise TimeoutError("upstream timeout")

        wrapped = with_error_handling(_failing, "governance_agent")
        result = await wrapped(_make_state())
        payload = json.loads(result["error"])

        assert payload["failed_node"] == "governance_agent"
        assert payload["error_type"] == "TimeoutError"
        assert payload["message"] == "upstream timeout"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_timestamp_is_iso8601_format(self) -> None:
        """The timestamp in the error payload must be a valid ISO-8601 UTC string."""
        import re

        _TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        async def _failing(state: AgentState) -> dict:
            raise RuntimeError("ts test")

        wrapped = with_error_handling(_failing, "compression_agent")
        result = await wrapped(_make_state())
        payload = json.loads(result["error"])
        assert _TS_RE.match(payload["timestamp"]), f"Not ISO-8601 Z: {payload['timestamp']}"


# ---------------------------------------------------------------------------
# failed_node correctness per pipeline node
# ---------------------------------------------------------------------------


class TestFailedNodePerPipelineNode:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("node_name", _PIPELINE_NODES)
    async def test_failed_node_in_error_payload(self, node_name: str) -> None:
        """Each of the 5 pipeline nodes must record its own name in failed_node."""
        async def _raise(state: AgentState) -> dict:
            raise RuntimeError(f"injected failure in {node_name}")

        wrapped = with_error_handling(_raise, node_name)
        result = await wrapped(_make_state())
        payload = json.loads(result["error"])

        assert payload["failed_node"] == node_name, (
            f"Expected failed_node={node_name!r}, got {payload['failed_node']!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("node_name", _PIPELINE_NODES)
    async def test_current_node_set_to_failing_node(self, node_name: str) -> None:
        """current_node in the returned dict must equal the failing node name."""
        async def _raise(state: AgentState) -> dict:
            raise RuntimeError("injected")

        wrapped = with_error_handling(_raise, node_name)
        result = await wrapped(_make_state())
        assert result["current_node"] == node_name


# ---------------------------------------------------------------------------
# pipeline_failed terminal node
# ---------------------------------------------------------------------------


class TestPipelineFailedTerminalNode:
    @pytest.mark.asyncio
    async def test_returns_failed_status(self) -> None:
        """failed_terminal_node must return status=FAILED."""
        state = _make_state(status=ExecutionStatus.FAILED, error='{"failed_node": "intent_agent"}')
        result = await failed_terminal_node(state)
        assert result["status"] == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_sets_current_node_to_pipeline_failed(self) -> None:
        """failed_terminal_node must set current_node='pipeline_failed'."""
        state = _make_state(status=ExecutionStatus.FAILED)
        result = await failed_terminal_node(state)
        assert result["current_node"] == "pipeline_failed"

    @pytest.mark.asyncio
    async def test_is_no_op_on_existing_error(self) -> None:
        """failed_terminal_node must not overwrite the existing error field."""
        error_payload = json.dumps({"failed_node": "retrieval_agent", "message": "test"})
        state = _make_state(status=ExecutionStatus.FAILED, error=error_payload)
        result = await failed_terminal_node(state)
        # Returns a partial dict — error not included, so existing state is preserved by LangGraph
        assert "error" not in result


# ---------------------------------------------------------------------------
# NodeWrapper.wrap — with_error_handling as innermost
# ---------------------------------------------------------------------------


class TestNodeWrapperWithErrorHandling:
    @pytest.mark.asyncio
    async def test_exception_in_raw_node_returns_failed_state(self) -> None:
        """NodeWrapper.wrap must catch exceptions via with_error_handling and return failed state."""
        async def _failing_intent(state: AgentState) -> dict:
            raise ValueError("intent extraction failed")

        wrapped = NodeWrapper.wrap(_failing_intent, "intent_agent")
        result = await wrapped(_make_state())

        assert result["status"] == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_exception_never_propagates_through_wrap(self) -> None:
        """NodeWrapper.wrap must not re-raise any exception from the raw node."""
        async def _raise(state: AgentState) -> dict:
            raise RuntimeError("should be swallowed")

        wrapped = NodeWrapper.wrap(_raise, "retrieval_agent")
        result = await wrapped(_make_state())
        # If it raised, test fails automatically
        assert result["status"] == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_error_json_preserved_through_wrap(self) -> None:
        """Error JSON produced by with_error_handling must survive the full wrap stack."""
        async def _raise(state: AgentState) -> dict:
            raise ConnectionRefusedError("Qdrant down")

        wrapped = NodeWrapper.wrap(_raise, "retrieval_agent")
        result = await wrapped(_make_state())

        payload = json.loads(result["error"])
        assert payload["failed_node"] == "retrieval_agent"
        assert payload["error_type"] == "ConnectionRefusedError"
        assert payload["message"] == "Qdrant down"

    @pytest.mark.asyncio
    async def test_intent_agent_failure_populates_correct_failed_node(self) -> None:
        """intent_agent exception must record 'intent_agent' as failed_node."""
        async def _raise(state: AgentState) -> dict:
            raise RuntimeError("NLP model timeout")

        wrapped = NodeWrapper.wrap(_raise, "intent_agent")
        result = await wrapped(_make_state())
        payload = json.loads(result["error"])
        assert payload["failed_node"] == "intent_agent"

    @pytest.mark.asyncio
    async def test_prometheus_histogram_records_failed_on_exception(self) -> None:
        """Histogram must record status='failed' when with_error_handling catches an exception."""
        # Use a real node name so node_contract can look it up in NODE_OUTPUT_CONTRACTS.
        node_name = "intent_agent"
        before = _histogram_count(node_name, "failed")

        async def _raise(state: AgentState) -> dict:
            raise RuntimeError("histogram test failure")

        wrapped = NodeWrapper.wrap(_raise, node_name)
        await wrapped(_make_state())

        after = _histogram_count(node_name, "failed")
        assert after == before + 1, f"Expected failed count +1; before={before}, after={after}"


# ---------------------------------------------------------------------------
# Mid-pipeline failure — downstream nodes must not execute
# ---------------------------------------------------------------------------


class TestMidPipelineFailureSkipsDownstreamNodes:
    @pytest.mark.asyncio
    async def test_retrieval_failure_skips_compression_and_routing(self) -> None:
        """When retrieval_agent fails, compression_agent and routing_agent must not run.

        Governance runs (unconditional edge from retrieval), but route_after_governance
        detects status=FAILED and routes to pipeline_failed, skipping compression and routing.
        """
        compression_mock = AsyncMock(return_value={"current_node": "compression_agent", "status": ExecutionStatus.RUNNING})
        routing_mock = AsyncMock(return_value={"current_node": "routing_agent", "status": ExecutionStatus.COMPLETE})
        # governance_mock returns minimal dict so it does NOT overwrite the FAILED status
        gov_mock = AsyncMock(return_value={"current_node": "governance_agent"})

        with (
            patch("src.agents.graph.retrieval_node", side_effect=RuntimeError("retrieval down")),
            patch("src.agents.graph.governance_node", gov_mock),
            patch("src.agents.graph.compression_node", compression_mock),
            patch("src.agents.graph.routing_node", routing_mock),
        ):
            graph = build_graph()
            state = _make_state(status=ExecutionStatus.PENDING, intent_confidence=0.9)
            final_state = await graph.ainvoke(state, config={"configurable": {"thread_id": "t-skip-test"}})

        compression_mock.assert_not_called()
        routing_mock.assert_not_called()
        assert final_state["status"] == ExecutionStatus.FAILED
        assert final_state["current_node"] == "pipeline_failed"

    @pytest.mark.asyncio
    async def test_intent_failure_skips_all_downstream_nodes(self) -> None:
        """When intent_agent fails, all downstream nodes must not execute."""
        retrieval_mock = AsyncMock(return_value={"current_node": "retrieval_agent", "status": ExecutionStatus.RUNNING})

        with (
            patch("src.agents.graph.intent_node", side_effect=RuntimeError("intent down")),
            patch("src.agents.graph.retrieval_node", retrieval_mock),
        ):
            graph = build_graph()
            state = _make_state(status=ExecutionStatus.PENDING)
            final_state = await graph.ainvoke(state, config={"configurable": {"thread_id": "t-intent-fail"}})

        retrieval_mock.assert_not_called()
        assert final_state["status"] == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_pipeline_failed_is_last_node_on_any_failure(self) -> None:
        """The pipeline_failed terminal node must always be the last node for any failure."""
        with patch("src.agents.graph.intent_node", side_effect=RuntimeError("crash")):
            graph = build_graph()
            state = _make_state(status=ExecutionStatus.PENDING)
            final_state = await graph.ainvoke(state, config={"configurable": {"thread_id": "t-terminal"}})

        assert final_state["current_node"] == "pipeline_failed"


# ---------------------------------------------------------------------------
# POST /v1/execute — structured error response for FAILED pipeline
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


class TestExecuteEndpointPipelineFailure:
    def test_pipeline_failed_state_returns_http_200_with_error_status(self) -> None:
        """POST /v1/execute must return HTTP 200 (not 500) when the pipeline fails."""
        error_payload = json.dumps({
            "failed_node": "retrieval_agent",
            "error_type": "ConnectionRefusedError",
            "message": "Connection refused to Qdrant",
            "timestamp": "2026-07-16T10:00:00Z",
        })
        failed_state: AgentState = _make_state(
            status=ExecutionStatus.FAILED,
            current_node="pipeline_failed",
            error=error_payload,
        )

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=failed_state)
        set_graph(mock_graph)

        app = _make_app()
        client = TestClient(app)
        response = client.post("/v1/execute", json=_SAMPLE_EXECUTE_REQUEST)

        assert response.status_code == 200

    def test_pipeline_failed_state_returns_error_status_field(self) -> None:
        """Response status must be 'error' when the pipeline has status=FAILED."""
        failed_state: AgentState = _make_state(
            status=ExecutionStatus.FAILED,
            current_node="pipeline_failed",
            error=json.dumps({"failed_node": "intent_agent", "message": "intent failed", "error_type": "RuntimeError", "timestamp": "2026-07-16T10:00:00Z"}),
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=failed_state)
        set_graph(mock_graph)

        app = _make_app()
        client = TestClient(app)
        response = client.post("/v1/execute", json=_SAMPLE_EXECUTE_REQUEST)
        body = response.json()

        assert body["status"] == "error"

    def test_pipeline_failed_state_includes_structured_error_detail(self) -> None:
        """Response error.data must contain the structured error payload."""
        error_payload = {
            "failed_node": "governance_agent",
            "error_type": "PermissionError",
            "message": "redaction policy violation",
            "timestamp": "2026-07-16T10:00:00Z",
        }
        failed_state: AgentState = _make_state(
            status=ExecutionStatus.FAILED,
            error=json.dumps(error_payload),
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=failed_state)
        set_graph(mock_graph)

        app = _make_app()
        client = TestClient(app)
        response = client.post("/v1/execute", json=_SAMPLE_EXECUTE_REQUEST)
        body = response.json()

        assert body["error"]["code"] == -32603
        assert body["error"]["message"] == "redaction policy violation"
        assert body["error"]["data"]["failed_node"] == "governance_agent"

    def test_pipeline_failed_state_uses_fallback_message_when_error_missing(self) -> None:
        """When error field is empty, message must default to 'Pipeline failed'."""
        failed_state: AgentState = _make_state(
            status=ExecutionStatus.FAILED,
            error=None,
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=failed_state)
        set_graph(mock_graph)

        app = _make_app()
        client = TestClient(app)
        response = client.post("/v1/execute", json=_SAMPLE_EXECUTE_REQUEST)
        body = response.json()

        assert body["status"] == "error"
        assert body["error"]["message"] == "Pipeline failed"

    def test_request_id_echoed_on_pipeline_failure(self) -> None:
        """request_id must be echoed in the response even when the pipeline fails."""
        failed_state: AgentState = _make_state(
            status=ExecutionStatus.FAILED,
            error=json.dumps({"failed_node": "routing_agent", "message": "m", "error_type": "E", "timestamp": "2026-07-16T10:00:00Z"}),
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=failed_state)
        set_graph(mock_graph)

        app = _make_app()
        client = TestClient(app)
        response = client.post("/v1/execute", json=_SAMPLE_EXECUTE_REQUEST)
        body = response.json()

        assert body["request_id"] == _SAMPLE_EXECUTE_REQUEST["request_id"]

    def test_exception_in_graph_still_returns_error_status(self) -> None:
        """Unhandled graph exceptions must still return HTTP 200 with status='error'."""
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("unexpected graph crash"))
        set_graph(mock_graph)

        app = _make_app()
        client = TestClient(app)
        response = client.post("/v1/execute", json=_SAMPLE_EXECUTE_REQUEST)

        assert response.status_code == 200
        assert response.json()["status"] == "error"
