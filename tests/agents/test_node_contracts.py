"""Unit tests for NodeWrapper, @node_contract, and ContractViolationError.

Coverage targets (TASK-US006-02 acceptance criteria):
  - valid output: node returning only allowed fields succeeds in both debug and prod mode
  - contract violation: node returning disallowed field raises ContractViolationError in debug mode
  - no enforcement in prod: same violation returns successfully when settings.debug=False
  - missing current_node: wrapper injects current_node automatically
  - identity field write: attempt to write request_id/user_id/prompt raises ContractViolationError
  - NODE_OUTPUT_CONTRACTS: all 5 nodes declared, identity fields absent from all
  - NodeWrapper.wrap: composition order — contract innermost, events outermost
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.nodes.base import ContractViolationError, NodeWrapper, node_contract
from src.agents.nodes.contracts import NODE_OUTPUT_CONTRACTS
from src.agents.state import AgentState, ExecutionStatus


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_IDENTITY_FIELDS = {"request_id", "user_id", "username", "roles", "tool_name", "prompt", "timestamp"}
_PIPELINE_NODES = {"intent_agent", "retrieval_agent", "governance_agent", "compression_agent", "routing_agent"}


def _make_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "req-test-001",
        "user_id": "user-test-001",
        "username": "tester",
        "roles": ["viewer"],
        "tool_name": "get_context",
        "prompt": "what is the auth flow?",
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


# ---------------------------------------------------------------------------
# NODE_OUTPUT_CONTRACTS correctness
# ---------------------------------------------------------------------------

class TestNodeOutputContracts:
    def test_all_five_nodes_declared(self) -> None:
        assert NODE_OUTPUT_CONTRACTS.keys() == _PIPELINE_NODES

    def test_identity_fields_absent_from_all_nodes(self) -> None:
        for node_name, allowed in NODE_OUTPUT_CONTRACTS.items():
            overlap = allowed & _IDENTITY_FIELDS
            assert overlap == set(), (
                f"Node '{node_name}' declares identity field(s) {overlap} — "
                "identity fields must never be writable by any node."
            )

    def test_universal_fields_present_in_all_nodes(self) -> None:
        universal = {"status", "current_node", "error"}
        for node_name, allowed in NODE_OUTPUT_CONTRACTS.items():
            assert universal <= allowed, (
                f"Node '{node_name}' is missing universal fields: {universal - allowed}"
            )


# ---------------------------------------------------------------------------
# @node_contract — debug mode ON
# ---------------------------------------------------------------------------

class TestNodeContractDebugMode:
    @pytest.fixture(autouse=True)
    def _enable_debug(self) -> None:
        with patch("src.agents.nodes.base.settings") as mock_settings:
            mock_settings.debug = True
            yield

    @pytest.mark.asyncio
    async def test_valid_output_passes(self) -> None:
        state = _make_state()

        @node_contract("intent_agent")
        async def good_node(s: AgentState) -> dict:
            return {
                "intent_type": "retrieval",
                "intent_confidence": 0.95,
                "execution_plan": {},
                "status": ExecutionStatus.RUNNING,
                "current_node": "intent_agent",
                "error": None,
            }

        result = await good_node(state)
        assert result["intent_type"] == "retrieval"

    @pytest.mark.asyncio
    async def test_disallowed_field_raises_contract_violation(self) -> None:
        state = _make_state()

        @node_contract("intent_agent")
        async def bad_node(s: AgentState) -> dict:
            return {
                "intent_type": "retrieval",
                "current_node": "intent_agent",
                "status": ExecutionStatus.RUNNING,
                "raw_context": [],  # belongs to retrieval_agent, not intent_agent
            }

        with pytest.raises(ContractViolationError) as exc_info:
            await bad_node(state)

        assert "raw_context" in str(exc_info.value)
        assert "intent_agent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_identity_field_write_raises_contract_violation(self) -> None:
        state = _make_state()

        @node_contract("intent_agent")
        async def identity_clobber(s: AgentState) -> dict:
            return {
                "intent_type": "retrieval",
                "current_node": "intent_agent",
                "status": ExecutionStatus.RUNNING,
                "request_id": "hacked-id",  # identity field — must never be writable
            }

        with pytest.raises(ContractViolationError) as exc_info:
            await identity_clobber(state)

        assert "request_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_current_node_injected_automatically(self) -> None:
        state = _make_state()

        @node_contract("retrieval_agent")
        async def forgetful_node(s: AgentState) -> dict:
            return {
                "raw_context": [{"chunk": "data"}],
                "status": ExecutionStatus.RUNNING,
                # current_node intentionally omitted
            }

        result = await forgetful_node(state)
        assert result["current_node"] == "retrieval_agent"

    @pytest.mark.asyncio
    async def test_error_field_always_permitted(self) -> None:
        state = _make_state()

        @node_contract("governance_agent")
        async def erroring_node(s: AgentState) -> dict:
            return {
                "status": ExecutionStatus.FAILED,
                "current_node": "governance_agent",
                "error": "policy engine unavailable",
            }

        result = await erroring_node(state)
        assert result["error"] == "policy engine unavailable"


# ---------------------------------------------------------------------------
# @node_contract — debug mode OFF (production)
# ---------------------------------------------------------------------------

class TestNodeContractProductionMode:
    @pytest.fixture(autouse=True)
    def _disable_debug(self) -> None:
        with patch("src.agents.nodes.base.settings") as mock_settings:
            mock_settings.debug = False
            yield

    @pytest.mark.asyncio
    async def test_disallowed_field_does_not_raise_in_production(self) -> None:
        state = _make_state()

        @node_contract("intent_agent")
        async def bad_node_prod(s: AgentState) -> dict:
            return {
                "intent_type": "retrieval",
                "current_node": "intent_agent",
                "status": ExecutionStatus.RUNNING,
                "raw_context": [],  # contract violation — silently ignored in production
            }

        # Must NOT raise — production has zero enforcement overhead.
        result = await bad_node_prod(state)
        assert "raw_context" in result

    @pytest.mark.asyncio
    async def test_missing_current_node_injected_in_production_too(self) -> None:
        state = _make_state()

        @node_contract("compression_agent")
        async def no_current_node(s: AgentState) -> dict:
            return {
                "compressed_context": [],
                "tokens_before_compression": 100,
                "tokens_after_compression": 60,
                "status": ExecutionStatus.RUNNING,
            }

        result = await no_current_node(state)
        assert result["current_node"] == "compression_agent"


# ---------------------------------------------------------------------------
# NodeWrapper.wrap — composition and integration
# ---------------------------------------------------------------------------

class TestNodeWrapperComposition:
    @pytest.fixture(autouse=True)
    def _enable_debug(self) -> None:
        with patch("src.agents.nodes.base.settings") as mock_settings:
            mock_settings.debug = True
            yield

    @pytest.mark.asyncio
    async def test_wrap_without_publisher_applies_contract(self) -> None:
        state = _make_state()

        async def routing_fn(s: AgentState) -> dict:
            return {
                "selected_model": "gpt-4o",
                "model_routing_score": 0.87,
                "final_response": {"answer": "42"},
                "status": ExecutionStatus.COMPLETE,
                "current_node": "routing_agent",
            }

        wrapped = NodeWrapper.wrap(routing_fn, "routing_agent")
        result = await wrapped(state)
        assert result["selected_model"] == "gpt-4o"
        assert result["current_node"] == "routing_agent"

    @pytest.mark.asyncio
    async def test_wrap_with_publisher_calls_state_events(self) -> None:
        state = _make_state()

        async def routing_fn(s: AgentState) -> dict:
            return {
                "selected_model": "gpt-4o",
                "final_response": {"answer": "42"},
                "status": ExecutionStatus.COMPLETE,
                "current_node": "routing_agent",
            }

        from src.agents.events.state_event_publisher import StateEventPublisher

        mock_producer = MagicMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)
        publisher = StateEventPublisher(mock_producer)

        wrapped = NodeWrapper.wrap(routing_fn, "routing_agent", publisher=publisher, is_final=True)
        result = await wrapped(state)

        assert result["selected_model"] == "gpt-4o"
        # with_state_events publishes 2 events (entry + success)
        assert mock_producer.send_and_wait.call_count == 2

    @pytest.mark.asyncio
    async def test_wrap_contract_violation_raised_before_events(self) -> None:
        """Contract check is innermost — violation prevents event publication."""
        state = _make_state()

        async def bad_routing_fn(s: AgentState) -> dict:
            return {
                "selected_model": "gpt-4o",
                "current_node": "routing_agent",
                "status": ExecutionStatus.RUNNING,
                "raw_context": [],  # not in routing_agent's contract
            }

        from src.agents.events.state_event_publisher import StateEventPublisher

        mock_producer = MagicMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)
        publisher = StateEventPublisher(mock_producer)

        wrapped = NodeWrapper.wrap(bad_routing_fn, "routing_agent", publisher=publisher)

        with pytest.raises(ContractViolationError):
            await wrapped(state)
