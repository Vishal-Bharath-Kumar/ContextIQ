"""Unit tests for StateEventPublisher and with_state_events node wrapper.

Coverage targets (TASK-US005-04 DoD ≥ 90% for events/state_event_publisher.py):
  - success path: entry + success events published with correct fields
  - node failure path: entry + failure event published, exception re-raised
  - publish failure: Kafka errors are swallowed, graph execution continues
  - is_final=True routing_agent: success event has to_status=COMPLETE
  - partition key: all events keyed by request_id
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.events.state_event_publisher import StateEventPublisher, with_state_events
from src.agents.events.state_event_schema import StateTransitionEvent
from src.agents.state import AgentState, ExecutionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "req-abc-123",
        "user_id": "user-xyz",
        "username": "tester",
        "roles": ["viewer"],
        "tool_name": "get_context",
        "prompt": "explain the auth flow",
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
    """Return a publisher wired to a fresh AsyncMock producer."""
    mock_producer = MagicMock()
    mock_producer.send_and_wait = AsyncMock(return_value=None)
    return StateEventPublisher(mock_producer), mock_producer


# ---------------------------------------------------------------------------
# StateTransitionEvent schema
# ---------------------------------------------------------------------------

class TestStateTransitionEventSchema:
    def test_required_fields(self) -> None:
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
        assert event.event_id == "e1"
        assert event.error is None

    def test_error_field_optional(self) -> None:
        event = StateTransitionEvent(
            event_id="e1",
            request_id="r1",
            user_id="u1",
            from_status="running",
            to_status="failed",
            node_name="intent_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=10,
            error="something went wrong",
        )
        assert event.error == "something went wrong"

    def test_model_dump_json_produces_valid_json(self) -> None:
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
        data = json.loads(event.model_dump_json())
        assert data["request_id"] == "r1"


# ---------------------------------------------------------------------------
# StateEventPublisher.publish
# ---------------------------------------------------------------------------

class TestStateEventPublisherPublish:
    @pytest.mark.asyncio
    async def test_publish_calls_send_and_wait_with_correct_args(self) -> None:
        publisher, mock_producer = _make_publisher()
        event = StateTransitionEvent(
            event_id="e1",
            request_id="req-abc-123",
            user_id="u1",
            from_status="pending",
            to_status="running",
            node_name="intent_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=0,
        )
        await publisher.publish(event)

        mock_producer.send_and_wait.assert_awaited_once()
        call_kwargs = mock_producer.send_and_wait.call_args
        assert call_kwargs.args[0] == StateEventPublisher.TOPIC
        assert call_kwargs.kwargs["key"] == b"req-abc-123"
        payload = json.loads(call_kwargs.kwargs["value"].decode())
        assert payload["event_id"] == "e1"
        assert call_kwargs.kwargs["headers"] == [("event_type", b"state.transition")]

    @pytest.mark.asyncio
    async def test_publish_failure_is_swallowed(self) -> None:
        """Kafka errors must NOT propagate — fire-and-forget."""
        publisher, mock_producer = _make_publisher()
        mock_producer.send_and_wait = AsyncMock(side_effect=RuntimeError("broker unavailable"))
        event = StateTransitionEvent(
            event_id="e1",
            request_id="req-abc-123",
            user_id="u1",
            from_status="pending",
            to_status="running",
            node_name="intent_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=0,
        )
        # Must not raise
        await publisher.publish(event)

    @pytest.mark.asyncio
    async def test_publish_failure_is_logged(self) -> None:
        publisher, mock_producer = _make_publisher()
        mock_producer.send_and_wait = AsyncMock(side_effect=OSError("network error"))
        event = StateTransitionEvent(
            event_id="e1",
            request_id="req-abc-123",
            user_id="u1",
            from_status="pending",
            to_status="running",
            node_name="intent_agent",
            timestamp="2026-07-16T00:00:00+00:00",
            duration_ms=0,
        )
        with patch("src.agents.events.state_event_publisher.logger") as mock_logger:
            await publisher.publish(event)
            mock_logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# with_state_events wrapper — success path
# ---------------------------------------------------------------------------

class TestWithStateEventsSuccess:
    @pytest.mark.asyncio
    async def test_entry_event_published_before_node_executes(self) -> None:
        publisher, mock_producer = _make_publisher()
        execution_order: list[str] = []

        async def _node(state: AgentState) -> AgentState:
            execution_order.append("node")
            return state

        mock_producer.send_and_wait = AsyncMock(
            side_effect=lambda *a, **kw: execution_order.append("publish") or None  # type: ignore[func-returns-value]
        )
        state = _make_state(status=ExecutionStatus.PENDING)
        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(state)

        # First publish call must happen before node body
        assert execution_order[0] == "publish"
        assert execution_order[1] == "node"

    @pytest.mark.asyncio
    async def test_entry_event_has_from_status_pending_to_running(self) -> None:
        publisher, mock_producer = _make_publisher()
        captured_events: list[dict] = []

        async def _capture(*args: object, **kwargs: object) -> None:
            payload = json.loads(kwargs["value"].decode())  # type: ignore[arg-type]
            captured_events.append(payload)

        mock_producer.send_and_wait = AsyncMock(side_effect=_capture)

        async def _node(state: AgentState) -> AgentState:
            return state

        state = _make_state(status=ExecutionStatus.PENDING)
        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(state)

        entry = captured_events[0]
        assert entry["from_status"] == "pending"
        assert entry["to_status"] == "running"
        assert entry["node_name"] == "intent_agent"
        assert entry["duration_ms"] == 0
        assert entry["request_id"] == "req-abc-123"

    @pytest.mark.asyncio
    async def test_success_event_intermediate_node_running(self) -> None:
        """Intermediate nodes emit RUNNING → RUNNING on success."""
        publisher, mock_producer = _make_publisher()
        captured_events: list[dict] = []

        async def _capture(*args: object, **kwargs: object) -> None:
            payload = json.loads(kwargs["value"].decode())  # type: ignore[arg-type]
            captured_events.append(payload)

        mock_producer.send_and_wait = AsyncMock(side_effect=_capture)

        async def _node(state: AgentState) -> AgentState:
            return state

        state = _make_state(status=ExecutionStatus.PENDING)
        wrapped = with_state_events(_node, "intent_agent", publisher, is_final=False)
        await wrapped(state)

        success_evt = captured_events[1]
        assert success_evt["from_status"] == "running"
        assert success_evt["to_status"] == "running"

    @pytest.mark.asyncio
    async def test_success_event_final_node_complete(self) -> None:
        """routing_agent (is_final=True) emits RUNNING → COMPLETE on success."""
        publisher, mock_producer = _make_publisher()
        captured_events: list[dict] = []

        async def _capture(*args: object, **kwargs: object) -> None:
            payload = json.loads(kwargs["value"].decode())  # type: ignore[arg-type]
            captured_events.append(payload)

        mock_producer.send_and_wait = AsyncMock(side_effect=_capture)

        async def _node(state: AgentState) -> AgentState:
            return state

        state = _make_state(status=ExecutionStatus.RUNNING)
        wrapped = with_state_events(_node, "routing_agent", publisher, is_final=True)
        await wrapped(state)

        success_evt = captured_events[1]
        assert success_evt["to_status"] == "complete"
        assert success_evt["node_name"] == "routing_agent"

    @pytest.mark.asyncio
    async def test_success_event_duration_ms_positive(self) -> None:
        publisher, mock_producer = _make_publisher()
        captured_events: list[dict] = []

        async def _capture(*args: object, **kwargs: object) -> None:
            payload = json.loads(kwargs["value"].decode())  # type: ignore[arg-type]
            captured_events.append(payload)

        mock_producer.send_and_wait = AsyncMock(side_effect=_capture)

        async def _node(state: AgentState) -> AgentState:
            return state

        state = _make_state()
        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(state)

        assert captured_events[1]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_two_events_published_on_success(self) -> None:
        publisher, mock_producer = _make_publisher()
        state = _make_state()

        async def _node(state: AgentState) -> AgentState:
            return state

        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(state)

        assert mock_producer.send_and_wait.await_count == 2

    @pytest.mark.asyncio
    async def test_all_events_keyed_by_request_id(self) -> None:
        """Partition key must equal request_id for all events."""
        publisher, mock_producer = _make_publisher()
        keys_seen: list[bytes] = []

        async def _capture(*args: object, **kwargs: object) -> None:
            keys_seen.append(kwargs["key"])  # type: ignore[arg-type]

        mock_producer.send_and_wait = AsyncMock(side_effect=_capture)

        async def _node(state: AgentState) -> AgentState:
            return state

        state = _make_state(request_id="req-partition-test")
        wrapped = with_state_events(_node, "intent_agent", publisher)
        await wrapped(state)

        assert all(k == b"req-partition-test" for k in keys_seen)

    @pytest.mark.asyncio
    async def test_wrapper_returns_node_result(self) -> None:
        publisher, _ = _make_publisher()
        expected = _make_state(status=ExecutionStatus.RUNNING)

        async def _node(state: AgentState) -> AgentState:
            return expected

        state = _make_state()
        wrapped = with_state_events(_node, "intent_agent", publisher)
        result = await wrapped(state)
        assert result is expected


# ---------------------------------------------------------------------------
# with_state_events wrapper — failure path
# ---------------------------------------------------------------------------

class TestWithStateEventsFailure:
    @pytest.mark.asyncio
    async def test_failure_event_published_on_exception(self) -> None:
        publisher, mock_producer = _make_publisher()
        captured_events: list[dict] = []

        async def _capture(*args: object, **kwargs: object) -> None:
            payload = json.loads(kwargs["value"].decode())  # type: ignore[arg-type]
            captured_events.append(payload)

        mock_producer.send_and_wait = AsyncMock(side_effect=_capture)

        async def _failing_node(state: AgentState) -> AgentState:
            raise ValueError("retrieval error")

        state = _make_state(status=ExecutionStatus.RUNNING)
        wrapped = with_state_events(_failing_node, "retrieval_agent", publisher)

        with pytest.raises(ValueError, match="retrieval error"):
            await wrapped(state)

        assert mock_producer.send_and_wait.await_count == 2
        failure_evt = captured_events[1]
        assert failure_evt["to_status"] == "failed"
        assert failure_evt["node_name"] == "retrieval_agent"
        assert failure_evt["error"] == "retrieval error"

    @pytest.mark.asyncio
    async def test_exception_is_reraised_after_failure_event(self) -> None:
        publisher, _ = _make_publisher()

        async def _failing_node(state: AgentState) -> AgentState:
            raise RuntimeError("downstream error")

        state = _make_state()
        wrapped = with_state_events(_failing_node, "governance_agent", publisher)

        with pytest.raises(RuntimeError, match="downstream error"):
            await wrapped(state)

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_block_pipeline_on_node_error(self) -> None:
        """Even when Kafka is down, the original exception propagates normally."""
        publisher, mock_producer = _make_publisher()
        mock_producer.send_and_wait = AsyncMock(side_effect=ConnectionError("kafka down"))

        async def _failing_node(state: AgentState) -> AgentState:
            raise ValueError("node error")

        state = _make_state()
        wrapped = with_state_events(_failing_node, "compression_agent", publisher)

        with pytest.raises(ValueError, match="node error"):
            await wrapped(state)

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise_on_success_path(self) -> None:
        """When Kafka is down on success path, graph execution continues normally."""
        publisher, mock_producer = _make_publisher()
        mock_producer.send_and_wait = AsyncMock(side_effect=ConnectionError("kafka down"))

        async def _node(state: AgentState) -> AgentState:
            return state

        state = _make_state()
        wrapped = with_state_events(_node, "intent_agent", publisher)
        # Must not raise
        result = await wrapped(state)
        assert result is state
