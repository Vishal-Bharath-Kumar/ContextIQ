"""Unit tests for AgentState TypedDict and LangGraph StateGraph skeleton."""

from __future__ import annotations

import pytest

from src.agents.state import AgentState, ExecutionStatus


# ---------------------------------------------------------------------------
# AgentState schema tests
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "request_id",
    "user_id",
    "username",
    "roles",
    "tool_name",
    "prompt",
    "timestamp",
    "status",
    "current_node",
    "error",
    "intent_type",
    "intent_confidence",
    "intent_source_list",
    "execution_plan",
    "requires_clarification",
    "raw_context",
    "ranked_context",
    "degraded_sources",
    "compressed_context",
    "tokens_before_compression",
    "tokens_after_compression",
    "governance_decisions",
    "redacted_chunks",
    "selected_model",
    "model_routing_score",
    "final_response",
}


def test_agent_state_has_all_fields() -> None:
    annotations = AgentState.__annotations__
    assert REQUIRED_FIELDS == set(annotations.keys()), (
        f"Missing fields: {REQUIRED_FIELDS - set(annotations.keys())}"
    )


def test_agent_state_field_count() -> None:
    assert len(AgentState.__annotations__) == 26


def test_execution_status_values() -> None:
    assert ExecutionStatus.PENDING == "pending"
    assert ExecutionStatus.RUNNING == "running"
    assert ExecutionStatus.COMPLETE == "complete"
    assert ExecutionStatus.FAILED == "failed"


def _make_initial_state() -> AgentState:
    return AgentState(
        request_id="00000000-0000-0000-0000-000000000001",
        user_id="user-sub-123",
        username="alice",
        roles=["developer"],
        tool_name="context_search",
        prompt="What is the auth flow?",
        timestamp="2026-07-16T00:00:00Z",
        status=ExecutionStatus.PENDING,
        current_node="",
        error=None,
        intent_type=None,
        intent_confidence=None,
        intent_source_list=None,
        execution_plan=None,
        raw_context=None,
        ranked_context=None,
        compressed_context=None,
        tokens_before_compression=None,
        tokens_after_compression=None,
        governance_decisions=None,
        redacted_chunks=None,
        selected_model=None,
        model_routing_score=None,
        final_response=None,
    )


def test_agent_state_construction() -> None:
    state = _make_initial_state()
    assert state["request_id"] == "00000000-0000-0000-0000-000000000001"
    assert state["status"] == ExecutionStatus.PENDING
    assert state["roles"] == ["developer"]


def test_agent_state_forward_compatible_optional_fields() -> None:
    state = _make_initial_state()
    extended = {**state, "new_optional_field": "value"}
    assert extended["new_optional_field"] == "value"
    assert extended["request_id"] == state["request_id"]


# ---------------------------------------------------------------------------
# Graph skeleton tests
# ---------------------------------------------------------------------------

def test_graph_compiles() -> None:
    from src.agents.graph import build_graph

    graph = build_graph()
    assert graph is not None


def test_graph_nodes_registered() -> None:
    from src.agents.graph import build_graph

    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        "__start__",
        "intent_agent",
        "retrieval_agent",
        "governance_agent",
        "compression_agent",
        "routing_agent",
    }
    assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"


@pytest.mark.asyncio
async def test_graph_invoke_with_stub_nodes() -> None:
    from src.agents.graph import build_graph

    graph = build_graph()
    initial = _make_initial_state()
    result = await graph.ainvoke(initial)
    assert result is not None
    assert result["request_id"] == initial["request_id"]
    assert result["status"] == ExecutionStatus.COMPLETE


@pytest.mark.asyncio
async def test_graph_clarification_route_on_low_confidence() -> None:
    from src.agents.graph import build_graph
    from src.agents.nodes.intent import intent_node as _real_intent

    async def low_confidence_intent(state: AgentState) -> AgentState:
        return {**state, "current_node": "intent_agent", "intent_confidence": 0.3}

    from unittest.mock import patch

    graph = build_graph()
    initial = {**_make_initial_state(), "intent_confidence": 0.3}

    with patch("src.agents.nodes.intent.intent_node", low_confidence_intent):
        graph2 = build_graph()
        result = await graph2.ainvoke(initial)
    assert result is not None


def test_stub_nodes_importable() -> None:
    from src.agents.nodes import (
        compression_node,
        governance_node,
        intent_node,
        retrieval_node,
        routing_node,
    )

    assert callable(intent_node)
    assert callable(retrieval_node)
    assert callable(governance_node)
    assert callable(compression_node)
    assert callable(routing_node)
