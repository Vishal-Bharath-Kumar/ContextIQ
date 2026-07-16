"""Unit tests for TASK-US009-04 — Low-Confidence Fallback and Clarification Routing.
TASK-US011-03 — `clarification_round` Counter and Recursive-Cap Guard.

Covers all four ``route_after_intent`` outcomes across {low/high confidence} ×
{round 0/round 1} combinations plus the FAILED short-circuit:
- ``"retrieval"``     — confidence ≥ INTENT_CONFIDENCE_THRESHOLD (0.60)
- ``"clarification"`` — confidence < threshold and clarification_round == 0
- ``"retrieval"``     — confidence < threshold and clarification_round >= 1 (cap)
- ``"failed"``        — status == ExecutionStatus.FAILED regardless of confidence

Also covers ``clarification_node`` behaviour and ``INTENT_CONFIDENCE_THRESHOLD``
being the single source of truth (imported, not duplicated).
"""

from __future__ import annotations

import pytest

from src.agents.config import INTENT_CONFIDENCE_THRESHOLD, MAX_CLARIFICATION_ROUNDS
from src.agents.nodes.clarification_node import clarification_node
from src.agents.routing import route_after_intent
from src.agents.schemas.intent import IntentType
from src.agents.state import AgentState, ExecutionStatus

# ── Helpers ───────────────────────────────────────────────────────────────────


def _base_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "req-us009-04",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "context_search",
        "prompt": "What is the deployment process?",
        "timestamp": "2026-07-16T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "intent_agent",
        "error": None,
        "intent_type": IntentType.GENERAL,
        "intent_confidence": 0.8,
        "intent_source_list": None,
        "execution_plan": None,
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
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


# ── route_after_intent ────────────────────────────────────────────────────────


class TestRouteAfterIntentBoundary:
    def test_boundary_at_threshold_routes_to_retrieval(self) -> None:
        """0.60 is exactly at threshold — must NOT trigger clarification."""
        state = _base_state(intent_confidence=0.60)
        assert route_after_intent(state) == "retrieval"

    def test_just_below_threshold_routes_to_clarification(self) -> None:
        """0.59 is below threshold — must trigger clarification."""
        state = _base_state(intent_confidence=0.59)
        assert route_after_intent(state) == "clarification"

    def test_failed_status_overrides_high_confidence(self) -> None:
        """FAILED status takes precedence over any confidence value."""
        state = _base_state(
            intent_confidence=0.99,
            status=ExecutionStatus.FAILED,
        )
        assert route_after_intent(state) == "failed"

    def test_failed_status_overrides_low_confidence(self) -> None:
        """FAILED status takes precedence even when confidence would clarify."""
        state = _base_state(
            intent_confidence=0.1,
            status=ExecutionStatus.FAILED,
        )
        assert route_after_intent(state) == "failed"

    def test_high_confidence_routes_to_retrieval(self) -> None:
        state = _base_state(intent_confidence=0.95)
        assert route_after_intent(state) == "retrieval"

    def test_zero_confidence_routes_to_clarification(self) -> None:
        state = _base_state(intent_confidence=0.0)
        assert route_after_intent(state) == "clarification"


class TestIntentConfidenceThresholdConstant:
    def test_threshold_constant_equals_point_six(self) -> None:
        """Single source of truth — constant must be 0.6."""
        assert INTENT_CONFIDENCE_THRESHOLD == 0.6

    def test_routing_uses_threshold_constant(self) -> None:
        """Boundary value derived from constant, not a magic number."""
        below = _base_state(intent_confidence=INTENT_CONFIDENCE_THRESHOLD - 0.001)
        at = _base_state(intent_confidence=INTENT_CONFIDENCE_THRESHOLD)
        assert route_after_intent(below) == "clarification"
        assert route_after_intent(at) == "retrieval"


# ── TASK-US011-03: clarification_round cap guard ──────────────────────────────


class TestRouteAfterIntentClarificationRoundCap:
    """Covers all four combinations: {low/high confidence} × {round 0/round 1}."""

    def test_low_confidence_round_0_routes_to_clarification(self) -> None:
        """First-pass low confidence must trigger clarification."""
        state = _base_state(intent_confidence=0.4, clarification_round=0)
        assert route_after_intent(state) == "clarification"

    def test_low_confidence_round_1_routes_to_retrieval(self) -> None:
        """Cap reached: second-pass low confidence must force retrieval."""
        state = _base_state(intent_confidence=0.4, clarification_round=1)
        assert route_after_intent(state) == "retrieval"

    def test_high_confidence_round_0_routes_to_retrieval(self) -> None:
        """High confidence at round 0 always goes to retrieval."""
        state = _base_state(intent_confidence=0.9, clarification_round=0)
        assert route_after_intent(state) == "retrieval"

    def test_high_confidence_round_1_routes_to_retrieval(self) -> None:
        """High confidence at round 1 always goes to retrieval."""
        state = _base_state(intent_confidence=0.9, clarification_round=1)
        assert route_after_intent(state) == "retrieval"

    def test_max_clarification_rounds_constant_equals_one(self) -> None:
        """Single source of truth — MAX_CLARIFICATION_ROUNDS must be 1."""
        assert MAX_CLARIFICATION_ROUNDS == 1

    def test_cap_uses_constant_not_inline_literal(self) -> None:
        """The cap threshold derives from MAX_CLARIFICATION_ROUNDS."""
        state = _base_state(
            intent_confidence=0.1,
            clarification_round=MAX_CLARIFICATION_ROUNDS,
        )
        assert route_after_intent(state) == "retrieval"

    def test_missing_clarification_round_defaults_to_round_0(self) -> None:
        """State without clarification_round key defaults to 0 (first pass)."""
        state = _base_state(intent_confidence=0.3)
        del state["clarification_round"]  # type: ignore[misc]
        assert route_after_intent(state) == "clarification"


# ── clarification_node ────────────────────────────────────────────────────────


class TestClarificationNode:
    @pytest.mark.asyncio
    async def test_sets_requires_clarification_true(self) -> None:
        state = _base_state(intent_confidence=0.45, intent_type=IntentType.DEBUGGING)
        result = await clarification_node(state)
        assert result["requires_clarification"] is True

    @pytest.mark.asyncio
    async def test_sets_status_complete(self) -> None:
        state = _base_state(intent_confidence=0.45)
        result = await clarification_node(state)
        assert result["status"] == ExecutionStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_final_response_type_is_clarification(self) -> None:
        state = _base_state(intent_confidence=0.3, intent_type=IntentType.CODE_GEN)
        result = await clarification_node(state)
        assert result["final_response"]["type"] == "clarification"

    @pytest.mark.asyncio
    async def test_final_response_message_includes_intent(self) -> None:
        state = _base_state(intent_confidence=0.42, intent_type=IntentType.INCIDENT)
        result = await clarification_node(state)
        assert "incident" in result["final_response"]["message"].lower()

    @pytest.mark.asyncio
    async def test_final_response_message_includes_confidence_percentage(self) -> None:
        state = _base_state(intent_confidence=0.42, intent_type=IntentType.GENERAL)
        result = await clarification_node(state)
        # 0.42 → "42%"
        assert "42%" in result["final_response"]["message"]

    @pytest.mark.asyncio
    async def test_unknown_intent_type_falls_back_to_unknown_string(self) -> None:
        state = _base_state(intent_confidence=0.3, intent_type=None)
        result = await clarification_node(state)
        assert "unknown" in result["final_response"]["message"]
