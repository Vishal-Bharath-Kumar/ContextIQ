"""Unit tests for execution_plan_snapshot extension to StateTransitionEvent.

Covers TASK-US010-05 acceptance criteria:
- StateTransitionEvent accepts execution_plan_snapshot as dict | None (default None).
- intent_agent success event carries a non-None execution_plan_snapshot.
- All other node transitions carry execution_plan_snapshot = None.
- model_dump_json() serialises execution_plan_snapshot correctly for Kafka payload.
- Existing event fields are backward-compatible (field is optional with default).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.events.state_event_publisher import StateEventPublisher, with_state_events
from src.agents.events.state_event_schema import StateTransitionEvent
from src.agents.schemas.execution_plan import ExecutionPlan, RankingStrategy
from src.agents.state import AgentState, ExecutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "req-snap-001",
        "user_id": "user-snap",
        "username": "tester",
        "roles": ["viewer"],
        "tool_name": "get_context",
        "prompt": "summarise the auth flow",
        "timestamp": "2026-07-16T00:00:00+00:00",
        "status": ExecutionStatus.PENDING,
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


def _make_publisher() -> tuple[StateEventPublisher, AsyncMock]:
    mock_producer = MagicMock()
    mock_producer.send_and_wait = AsyncMock(return_value=None)
    return StateEventPublisher(mock_producer), mock_producer


def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        sources=["confluence", "jira"],
        token_budget_total=8_000,
        token_budget_per_source={"confluence": 4_000, "jira": 4_000},
        ranking_strategy=RankingStrategy.HYBRID,
        cache_eligible=True,
    )


def _captured_events(mock_producer: AsyncMock) -> list[dict]:
    events = []
    for call in mock_producer.send_and_wait.call_args_list:
        payload = json.loads(call.kwargs["value"].decode())
        events.append(payload)
    return events


# ---------------------------------------------------------------------------
# Schema — execution_plan_snapshot field
# ---------------------------------------------------------------------------

class TestExecutionPlanSnapshotField:
    def test_default_is_none(self) -> None:
        event = StateTransitionEvent(
            event_id="e1",
            request_id="r1",
            user_id="u1",
            from_status="pending",
            to_status="running",
            node_name="intent_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=0,
        )
        assert event.execution_plan_snapshot is None

    def test_accepts_dict_value(self) -> None:
        snapshot = {"sources": ["confluence"], "token_budget_total": 8000}
        event = StateTransitionEvent(
            event_id="e1",
            request_id="r1",
            user_id="u1",
            from_status="running",
            to_status="running",
            node_name="intent_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=5,
            execution_plan_snapshot=snapshot,
        )
        assert event.execution_plan_snapshot == snapshot

    def test_model_dump_json_includes_snapshot(self) -> None:
        snapshot = {"sources": ["wiki"], "token_budget_total": 4000}
        event = StateTransitionEvent(
            event_id="e2",
            request_id="r2",
            user_id="u2",
            from_status="running",
            to_status="running",
            node_name="intent_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=3,
            execution_plan_snapshot=snapshot,
        )
        data = json.loads(event.model_dump_json())
        assert data["execution_plan_snapshot"] == snapshot

    def test_model_dump_json_null_when_none(self) -> None:
        event = StateTransitionEvent(
            event_id="e3",
            request_id="r3",
            user_id="u3",
            from_status="pending",
            to_status="running",
            node_name="retrieval_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=0,
        )
        data = json.loads(event.model_dump_json())
        assert data["execution_plan_snapshot"] is None

    def test_backward_compatible_existing_fields_unchanged(self) -> None:
        """Existing required fields remain unchanged; new field is optional."""
        event = StateTransitionEvent(
            event_id="e4",
            request_id="r4",
            user_id="u4",
            from_status="running",
            to_status="failed",
            node_name="governance_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=12,
            error="timeout",
        )
        assert event.error == "timeout"
        assert event.execution_plan_snapshot is None


# ---------------------------------------------------------------------------
# with_state_events — intent_agent snapshot population
# ---------------------------------------------------------------------------

class TestIntentAgentSnapshotPublishing:
    @pytest.mark.asyncio
    async def test_intent_agent_success_event_contains_snapshot(self) -> None:
        plan = _make_plan()

        async def _intent_node(state: AgentState) -> dict:
            return {
                "execution_plan": plan,
                "intent_type": "docs",
                "intent_confidence": 0.9,
                "current_node": "intent_agent",
                "status": ExecutionStatus.RUNNING,
            }

        publisher, mock_producer = _make_publisher()
        state = _make_state()
        wrapped = with_state_events(_intent_node, "intent_agent", publisher)
        await wrapped(state)

        events = _captured_events(mock_producer)
        # Two events: entry (index 0) + success (index 1)
        success_event = events[1]
        assert success_event["node_name"] == "intent_agent"
        snap = success_event["execution_plan_snapshot"]
        assert snap is not None
        required_keys = {
            "sources", "token_budget_total",
            "token_budget_per_source", "ranking_strategy", "cache_eligible",
        }
        assert set(snap.keys()) >= required_keys
        assert snap["sources"] == ["confluence", "jira"]
        assert snap["token_budget_total"] == 8_000
        assert snap["cache_eligible"] is True

    @pytest.mark.asyncio
    async def test_intent_agent_snapshot_keys_match_execution_plan(self) -> None:
        plan = _make_plan()

        async def _node(state: AgentState) -> dict:
            return {"execution_plan": plan, "current_node": "intent_agent", "status": ExecutionStatus.RUNNING}

        publisher, mock_producer = _make_publisher()
        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(_make_state())

        snap = _captured_events(mock_producer)[1]["execution_plan_snapshot"]
        assert snap == plan.model_dump()

    @pytest.mark.asyncio
    async def test_intent_agent_no_plan_in_result_snapshot_is_none(self) -> None:
        """If intent_node returns no execution_plan, snapshot stays None."""

        async def _node(state: AgentState) -> dict:
            return {"current_node": "intent_agent", "status": ExecutionStatus.RUNNING}

        publisher, mock_producer = _make_publisher()
        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(_make_state())

        snap = _captured_events(mock_producer)[1]["execution_plan_snapshot"]
        assert snap is None

    @pytest.mark.asyncio
    async def test_intent_agent_entry_event_snapshot_is_none(self) -> None:
        """Entry event (before node runs) always has None snapshot."""

        async def _node(state: AgentState) -> dict:
            return {"execution_plan": _make_plan(), "current_node": "intent_agent", "status": ExecutionStatus.RUNNING}

        publisher, mock_producer = _make_publisher()
        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(_make_state())

        entry_event = _captured_events(mock_producer)[0]
        assert entry_event["execution_plan_snapshot"] is None


# ---------------------------------------------------------------------------
# with_state_events — non-intent nodes must not include snapshot
# ---------------------------------------------------------------------------

class TestNonIntentNodeSnapshotIsNone:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "node_name",
        [
            "retrieval_agent",
            "governance_agent",
            "compression_agent",
            "routing_agent",
            "clarification_response",
            "pipeline_failed",
        ],
    )
    async def test_non_intent_node_success_snapshot_is_none(self, node_name: str) -> None:
        plan = _make_plan()

        async def _node(state: AgentState) -> dict:
            # Even if state contains an execution_plan, non-intent nodes must
            # not include it in their published event.
            return {"current_node": node_name, "status": ExecutionStatus.RUNNING}

        publisher, mock_producer = _make_publisher()
        # Pre-load execution_plan in state to prove it is ignored
        state = _make_state(execution_plan=plan)
        is_final = node_name in {"routing_agent"}
        wrapped = with_state_events(_node, node_name, publisher, is_final=is_final)
        await wrapped(state)

        success_event = _captured_events(mock_producer)[1]
        assert success_event["execution_plan_snapshot"] is None, (
            f"Node '{node_name}' must not set execution_plan_snapshot"
        )
