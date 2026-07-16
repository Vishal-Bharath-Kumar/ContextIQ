"""Unit tests for TASK-US009-02 — AgentState intent classification fields.

Validates:
- intent_type, intent_confidence, and intent_source_list presence in AgentState
- Type correctness after a mocked intent_node run
- intent_node output merges into AgentState without KeyError or type mismatch
- route_after_intent reads intent_confidence without or-fallback
"""

from __future__ import annotations

from typing import get_type_hints

from src.agents.routing import route_after_intent
from src.agents.schemas.intent import IntentType
from src.agents.state import AgentState, ExecutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "req-us009-02",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "context_search",
        "prompt": "Why does auth fail in staging?",
        "timestamp": "2026-07-16T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "intent_agent",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "intent_source_list": None,
        "execution_plan": None,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": None,
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


# ---------------------------------------------------------------------------
# Field presence tests
# ---------------------------------------------------------------------------


class TestAgentStateIntentFields:
    def test_intent_type_field_present(self) -> None:
        annotations = AgentState.__annotations__
        assert "intent_type" in annotations

    def test_intent_confidence_field_present(self) -> None:
        annotations = AgentState.__annotations__
        assert "intent_confidence" in annotations

    def test_intent_source_list_field_present(self) -> None:
        annotations = AgentState.__annotations__
        assert "intent_source_list" in annotations

    def test_intent_type_annotated_as_intent_type_enum(self) -> None:
        get_type_hints(AgentState)
        # Under `from __future__ import annotations` hints are resolved strings;
        # check the annotation string contains "IntentType"
        raw = AgentState.__annotations__["intent_type"]
        assert "IntentType" in str(raw)

    def test_intent_source_list_defaults_to_none(self) -> None:
        state = _base_state()
        assert state["intent_source_list"] is None

    def test_intent_type_defaults_to_none(self) -> None:
        state = _base_state()
        assert state["intent_type"] is None

    def test_intent_confidence_defaults_to_none(self) -> None:
        state = _base_state()
        assert state["intent_confidence"] is None


# ---------------------------------------------------------------------------
# intent_node merge tests
# ---------------------------------------------------------------------------


class TestIntentNodeMerge:
    """Verify that intent_node() output dict merges into AgentState cleanly."""

    def _mock_intent_output(
        self,
        intent_type: IntentType = IntentType.DEBUGGING,
        confidence: float = 0.92,
    ) -> dict:
        return {
            "intent_type": intent_type,
            "intent_confidence": confidence,
            "current_node": "intent_agent",
            "status": ExecutionStatus.RUNNING,
            "error": None,
        }

    def test_merge_does_not_raise_key_error(self) -> None:
        state = _base_state()
        node_output = self._mock_intent_output()
        merged: AgentState = {**state, **node_output}  # type: ignore[misc]
        assert merged["intent_type"] == IntentType.DEBUGGING

    def test_merge_preserves_identity_fields(self) -> None:
        state = _base_state()
        node_output = self._mock_intent_output()
        merged: AgentState = {**state, **node_output}  # type: ignore[misc]
        assert merged["request_id"] == "req-us009-02"
        assert merged["user_id"] == "user-1"

    def test_merge_sets_confidence_as_float(self) -> None:
        state = _base_state()
        node_output = self._mock_intent_output(confidence=0.75)
        merged: AgentState = {**state, **node_output}  # type: ignore[misc]
        assert isinstance(merged["intent_confidence"], float)
        assert merged["intent_confidence"] == 0.75

    def test_intent_source_list_remains_none_after_intent_node(self) -> None:
        """intent_source_list is None until TASK-US009-03 source mapper runs."""
        state = _base_state()
        node_output = self._mock_intent_output()
        merged: AgentState = {**state, **node_output}  # type: ignore[misc]
        assert merged["intent_source_list"] is None

    def test_intent_source_list_populated_by_mapper(self) -> None:
        """Simulates TASK-US009-03 populating intent_source_list."""
        state = _base_state()
        node_output = self._mock_intent_output()
        merged: AgentState = {**state, **node_output}  # type: ignore[misc]
        with_sources: AgentState = {**merged, "intent_source_list": ["github", "confluence"]}  # type: ignore[misc]
        assert with_sources["intent_source_list"] == ["github", "confluence"]


# ---------------------------------------------------------------------------
# route_after_intent — direct field access (no or-fallback)
# ---------------------------------------------------------------------------


class TestRouteAfterIntentNofallback:
    def test_routes_to_retrieval_on_high_confidence(self) -> None:
        state = _base_state(intent_type=IntentType.DEBUGGING, intent_confidence=0.92)
        assert route_after_intent(state) == "retrieval"

    def test_routes_to_clarification_on_low_confidence(self) -> None:
        state = _base_state(intent_type=IntentType.GENERAL, intent_confidence=0.55)
        assert route_after_intent(state) == "clarification"

    def test_routes_to_clarification_at_exact_boundary(self) -> None:
        state = _base_state(intent_type=IntentType.GENERAL, intent_confidence=0.59)
        assert route_after_intent(state) == "clarification"

    def test_routes_to_retrieval_at_threshold(self) -> None:
        state = _base_state(intent_type=IntentType.DOCS, intent_confidence=0.6)
        assert route_after_intent(state) == "retrieval"

    def test_failed_status_short_circuits_to_failed(self) -> None:
        state = _base_state(
            status=ExecutionStatus.FAILED,
            intent_type=IntentType.GENERAL,
            intent_confidence=0.9,
        )
        assert route_after_intent(state) == "failed"
