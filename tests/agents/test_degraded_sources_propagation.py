"""Unit tests for TASK-US008-03: degraded_sources propagation through the pipeline.

Coverage targets:
  - degraded_sources from retrieval node survives to final AgentState
  - governance_agent may append to degraded_sources (contract allows it)
  - compression_agent and routing_agent do NOT clear degraded_sources
  - ExecuteResponse.output always contains a degraded_sources key
  - All-connectors-failed: HTTP 200, empty output context, non-empty degraded_sources
  - ToolCallOutput.degraded_sources serialised correctly (source_id, error_type, message)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_worker.routers.execute import get_graph, router, set_graph
from src.agent_worker.schemas.execute_types import DegradedSourceSummary as WorkerDegradedSummary
from src.agents.nodes.contracts import NODE_OUTPUT_CONTRACTS
from src.agents.state import AgentState, DegradedSourceInfo, ExecutionStatus
from src.gateway.schemas.call_types import DegradedSourceSummary, ToolCallOutput

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASE_REQUEST = {
    "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "user_id": "user-sub-999",
    "username": "dev",
    "roles": ["developer"],
    "tool_name": "context_search",
    "arguments": {"prompt": "What is the auth flow?"},
    "trace_id": "b" * 32,
}

_DEGRADED: list[DegradedSourceInfo] = [
    {
        "source_id": "jira:myproject",
        "error_type": "ConnectorTimeoutError",
        "message": "Connector 'jira:myproject' timed out after 5.0s",
    }
]

_BASE_STATE: AgentState = {
    "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "user_id": "user-sub-999",
    "username": "dev",
    "roles": ["developer"],
    "tool_name": "context_search",
    "prompt": "What is the auth flow?",
    "timestamp": "2026-07-16T00:00:00Z",
    "status": ExecutionStatus.COMPLETE,
    "current_node": "routing_agent",
    "error": None,
    "intent_type": "question_answering",
    "intent_confidence": 0.9,
    "execution_plan": None,
    "raw_context": None,
    "ranked_context": None,
    "compressed_context": None,
    "tokens_before_compression": None,
    "tokens_after_compression": None,
    "governance_decisions": None,
    "redacted_chunks": None,
    "selected_model": "gpt-4o",
    "model_routing_score": 0.85,
    "final_response": {"context": [{"chunk_id": "c1", "content": "auth uses Keycloak"}]},
    "degraded_sources": None,
}


def _make_client(final_state: AgentState) -> tuple[TestClient, MagicMock]:
    """Return a (TestClient, mock_graph) pair for the given final state."""
    import src.agent_worker.routers.execute as execute_module

    app = FastAPI()
    app.include_router(router)

    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=final_state)
    app.dependency_overrides[get_graph] = lambda: graph
    set_graph(graph)

    client = TestClient(app)
    # Cleanup after yield is not supported for tuples; caller must tolerate module state.
    # Reset the module-level graph so tests don't bleed.
    execute_module._compiled_graph = None
    return client, graph


# ---------------------------------------------------------------------------
# 1. AgentState schema — DegradedSourceInfo TypedDict present
# ---------------------------------------------------------------------------


def test_agent_state_has_degraded_sources_field() -> None:
    """AgentState TypedDict must declare degraded_sources."""
    annotations = AgentState.__annotations__
    assert "degraded_sources" in annotations, "AgentState must declare degraded_sources"


def test_degraded_source_info_fields() -> None:
    """DegradedSourceInfo must have source_id, error_type, message."""
    expected = {"source_id", "error_type", "message"}
    assert set(DegradedSourceInfo.__annotations__) == expected


# ---------------------------------------------------------------------------
# 2. Node output contracts
# ---------------------------------------------------------------------------


def test_governance_agent_contract_includes_degraded_sources() -> None:
    """governance_agent may append to degraded_sources — must be in its contract."""
    assert "degraded_sources" in NODE_OUTPUT_CONTRACTS["governance_agent"]


def test_compression_agent_contract_excludes_degraded_sources() -> None:
    """compression_agent is read-only w.r.t. degraded_sources — must NOT be in its contract."""
    assert "degraded_sources" not in NODE_OUTPUT_CONTRACTS["compression_agent"]


def test_routing_agent_contract_excludes_degraded_sources() -> None:
    """routing_agent is read-only w.r.t. degraded_sources — must NOT be in its contract."""
    assert "degraded_sources" not in NODE_OUTPUT_CONTRACTS["routing_agent"]


def test_retrieval_agent_contract_includes_degraded_sources() -> None:
    """retrieval_agent is the primary writer of degraded_sources."""
    assert "degraded_sources" in NODE_OUTPUT_CONTRACTS["retrieval_agent"]


# ---------------------------------------------------------------------------
# 3. execute.py — degraded_sources in response output
# ---------------------------------------------------------------------------


def test_success_response_always_contains_degraded_sources_key() -> None:
    """ExecuteResponse.output always has a degraded_sources key (empty list on no failures)."""
    state = {**_BASE_STATE, "degraded_sources": None}
    client, _ = _make_client(state)  # type: ignore[arg-type]

    resp = client.post("/v1/execute", json=_BASE_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "degraded_sources" in body["output"]
    assert body["output"]["degraded_sources"] == []


def test_degraded_sources_propagated_in_response() -> None:
    """A single timed-out connector is surfaced in ExecuteResponse.output.degraded_sources."""
    state = {**_BASE_STATE, "degraded_sources": _DEGRADED}
    client, _ = _make_client(state)  # type: ignore[arg-type]

    resp = client.post("/v1/execute", json=_BASE_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    degraded = body["output"]["degraded_sources"]
    assert len(degraded) == 1
    assert degraded[0]["source_id"] == "jira:myproject"
    assert degraded[0]["error_type"] == "ConnectorTimeoutError"
    assert "timed out" in degraded[0]["message"]


def test_all_connectors_failed_returns_200_with_empty_context() -> None:
    """All-connectors-failed: HTTP 200, empty context, non-empty degraded_sources."""
    state = {
        **_BASE_STATE,
        "final_response": {"context": []},
        "degraded_sources": _DEGRADED,
    }
    client, _ = _make_client(state)  # type: ignore[arg-type]

    resp = client.post("/v1/execute", json=_BASE_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["output"]["context"] == []
    assert len(body["output"]["degraded_sources"]) == 1


# ---------------------------------------------------------------------------
# 4. ToolCallOutput schema — DegradedSourceSummary model
# ---------------------------------------------------------------------------


def test_tool_call_output_degraded_sources_default_empty() -> None:
    """ToolCallOutput.degraded_sources defaults to empty list."""
    out = ToolCallOutput(data={"context": []})
    assert out.degraded_sources == []


def test_tool_call_output_degraded_sources_serialised() -> None:
    """ToolCallOutput serialises degraded_sources correctly in model_dump."""
    summary = DegradedSourceSummary(
        source_id="jira:myproject",
        error_type="ConnectorTimeoutError",
        message="timed out after 5.0s",
    )
    out = ToolCallOutput(data={"context": []}, degraded_sources=[summary])
    dumped = out.model_dump()
    assert dumped["degraded_sources"] == [
        {
            "source_id": "jira:myproject",
            "error_type": "ConnectorTimeoutError",
            "message": "timed out after 5.0s",
        }
    ]


def test_degraded_source_summary_fields_gateway() -> None:
    """DegradedSourceSummary (gateway) must expose source_id, error_type, message."""
    s = DegradedSourceSummary(
        source_id="github:repo",
        error_type="ConnectorCircuitOpenError",
        message="circuit open",
    )
    assert s.source_id == "github:repo"
    assert s.error_type == "ConnectorCircuitOpenError"
    assert s.message == "circuit open"


# ---------------------------------------------------------------------------
# 5. execute_types.py — DegradedSourceSummary present
# ---------------------------------------------------------------------------


def test_worker_degraded_source_summary_model() -> None:
    """DegradedSourceSummary must exist in execute_types and validate correctly."""
    s = WorkerDegradedSummary(
        source_id="confluence:space",
        error_type="ConnectorTimeoutError",
        message="timed out",
    )
    assert s.source_id == "confluence:space"
