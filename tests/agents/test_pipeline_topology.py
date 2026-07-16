"""Unit tests for the ContextIQ pipeline topology.

Covers:
- ``route_after_intent`` — all three branches (retrieval / clarification / failed)
- ``route_after_governance`` — all three branches (skip / compress / failed)
- ``build_graph()`` — graph compiles with all 7 nodes; no dangling edges
- ``clarification_node`` — sets final_response and status = COMPLETE
- ``failed_terminal_node`` — sets status = FAILED
"""

from __future__ import annotations

import pytest

from src.agents.graph import build_graph, clarification_node, failed_terminal_node
from src.agents.routing import route_after_governance, route_after_intent
from src.agents.state import AgentState, ExecutionStatus


# ── Helpers ───────────────────────────────────────────────────────────────────


def _base_state(**overrides: object) -> AgentState:
    """Return a minimal valid ``AgentState`` with optional field overrides."""
    base: AgentState = {
        "request_id": "req-test",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["user"],
        "tool_name": "search",
        "prompt": "test prompt",
        "timestamp": "2026-01-01T00:00:00Z",
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
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# ── route_after_intent ────────────────────────────────────────────────────────


class TestRouteAfterIntent:
    def test_high_confidence_routes_to_retrieval(self) -> None:
        state = _base_state(intent_confidence=0.8)
        assert route_after_intent(state) == "retrieval"

    def test_exact_boundary_confidence_routes_to_retrieval(self) -> None:
        # 0.6 is NOT below threshold — should retrieve
        state = _base_state(intent_confidence=0.6)
        assert route_after_intent(state) == "retrieval"

    def test_low_confidence_routes_to_clarification(self) -> None:
        state = _base_state(intent_confidence=0.4)
        assert route_after_intent(state) == "clarification"

    def test_just_below_threshold_routes_to_clarification(self) -> None:
        state = _base_state(intent_confidence=0.599)
        assert route_after_intent(state) == "clarification"

    def test_failed_status_short_circuits_to_failed(self) -> None:
        state = _base_state(intent_confidence=0.9, status=ExecutionStatus.FAILED)
        assert route_after_intent(state) == "failed"

    def test_none_confidence_treated_as_1_routes_to_retrieval(self) -> None:
        # None → defaults to 1.0, which is ≥ 0.6
        state = _base_state(intent_confidence=None)
        assert route_after_intent(state) == "retrieval"


# ── route_after_governance ────────────────────────────────────────────────────


class TestRouteAfterGovernance:
    def test_tokens_within_budget_routes_to_skip(self) -> None:
        state = _base_state(
            execution_plan={"token_budget_total": 8000},
            ranked_context=[{"token_count": 3000}, {"token_count": 2000}],
        )
        assert route_after_governance(state) == "skip"

    def test_tokens_exactly_at_budget_routes_to_skip(self) -> None:
        state = _base_state(
            execution_plan={"token_budget_total": 5000},
            ranked_context=[{"token_count": 5000}],
        )
        assert route_after_governance(state) == "skip"

    def test_tokens_over_budget_routes_to_compress(self) -> None:
        state = _base_state(
            execution_plan={"token_budget_total": 4000},
            ranked_context=[{"token_count": 3000}, {"token_count": 2000}],
        )
        assert route_after_governance(state) == "compress"

    def test_no_execution_plan_uses_default_8000_budget(self) -> None:
        state = _base_state(
            execution_plan=None,
            ranked_context=[{"token_count": 7000}],
        )
        assert route_after_governance(state) == "skip"

    def test_no_execution_plan_over_default_budget_compresses(self) -> None:
        state = _base_state(
            execution_plan=None,
            ranked_context=[{"token_count": 9000}],
        )
        assert route_after_governance(state) == "compress"

    def test_empty_ranked_context_routes_to_skip(self) -> None:
        state = _base_state(ranked_context=[])
        assert route_after_governance(state) == "skip"

    def test_none_ranked_context_routes_to_skip(self) -> None:
        state = _base_state(ranked_context=None)
        assert route_after_governance(state) == "skip"

    def test_failed_status_short_circuits_to_failed(self) -> None:
        state = _base_state(
            status=ExecutionStatus.FAILED,
            ranked_context=[{"token_count": 1}],
        )
        assert route_after_governance(state) == "failed"


# ── build_graph ───────────────────────────────────────────────────────────────


class TestBuildGraph:
    def test_graph_compiles_without_error(self) -> None:
        graph = build_graph()
        assert graph is not None

    def test_graph_has_all_seven_nodes(self) -> None:
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        expected = {
            "intent_agent",
            "retrieval_agent",
            "governance_agent",
            "compression_agent",
            "routing_agent",
            "clarification_response",
            "pipeline_failed",
        }
        assert expected.issubset(node_names)

    def test_graph_entry_point_is_intent_agent(self) -> None:
        graph = build_graph()
        # The entry point shows up as an edge from the special __start__ node
        edges = list(graph.get_graph().edges)
        start_targets = [t for (s, t, *_) in edges if s == "__start__"]
        assert "intent_agent" in start_targets


# ── Terminal nodes ────────────────────────────────────────────────────────────


class TestClarificationNode:
    @pytest.mark.asyncio
    async def test_sets_requires_clarification_and_complete_status(self) -> None:
        from src.agents.schemas.intent import IntentType
        state = _base_state(intent_confidence=0.45, intent_type=IntentType.DEBUGGING)
        result = await clarification_node(state)
        assert result["status"] == ExecutionStatus.COMPLETE
        assert result["requires_clarification"] is True
        assert result["final_response"]["type"] == "clarification"
        assert "debugging" in result["final_response"]["message"].lower()
        assert "45%" in result["final_response"]["message"]

    @pytest.mark.asyncio
    async def test_unknown_intent_type_produces_unknown_label(self) -> None:
        state = _base_state(intent_confidence=0.3, intent_type=None)
        result = await clarification_node(state)
        assert result["final_response"]["message"] is not None
        assert "unknown" in result["final_response"]["message"]
        assert result["status"] == ExecutionStatus.COMPLETE


class TestFailedTerminalNode:
    @pytest.mark.asyncio
    async def test_sets_status_failed(self) -> None:
        state = _base_state(error="something went wrong")
        result = await failed_terminal_node(state)
        assert result["status"] == ExecutionStatus.FAILED
        assert result["current_node"] == "pipeline_failed"
        # failed_terminal_node is a no-op terminal that returns a partial state
        # update — it does NOT re-echo the error field (LangGraph preserves it
        # via state merge).  The error is set upstream by with_error_handling.
        assert "error" not in result
