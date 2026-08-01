from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.nodes.llm_response import llm_response_node
from src.agents.schemas.intent import IntentType
from src.agents.state import AgentState, ExecutionStatus
from src.model_invoker.schemas.fallback_chain import InvocationFailure
from src.model_invoker.schemas.llm_response import LLMResponse
from src.model_registry.schemas.model_definition import LatencyTier


def _make_state(**overrides: object) -> AgentState:
    state: AgentState = {
        "request_id": "req-llm-response",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "context_query",
        "prompt": "Explain why login is failing.",
        "timestamp": "2026-08-01T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "routing_agent",
        "error": None,
        "intent_type": IntentType.DEBUGGING,
        "intent_confidence": 0.92,
        "intent_source_list": ["github", "jira"],
        "execution_plan": {"token_budget_total": 4000},
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": [],
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": "gpt-4o",
        "model_routing_score": 0.87,
        "fallback_chain": ["gpt-4o", "gpt-4o-mini"],
        "final_response": {
            "type": "context_package",
            "prompt": "Explain why login is failing.",
            "intent": "debugging",
            "selected_model": "gpt-4o",
            "model_routing_score": 0.87,
            "context": [
                {
                    "source_id": "github",
                    "path": "src/auth/dev_login.py",
                    "content": "The login endpoint exchanges credentials with Keycloak.",
                }
            ],
            "governance": {"summary": "No blocking governance findings."},
            "degraded_sources": [],
        },
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


class TestLLMResponseNode:
    @pytest.mark.asyncio
    async def test_returns_llm_response_when_invocation_succeeds(self) -> None:
        runtime = SimpleNamespace(
            fallback_invoker=MagicMock(),
            get_model_definition=AsyncMock(
                return_value=SimpleNamespace(latency_tier=LatencyTier.MEDIUM)
            ),
        )
        runtime.fallback_invoker.invoke = AsyncMock(
            return_value=LLMResponse(
                model_id="gpt-4o",
                content="Login fails because the Keycloak token exchange is returning 503.",
                input_tokens=321,
                output_tokens=42,
                finish_reason="stop",
            )
        )
        state = _make_state(_config={"routing_runtime": runtime})

        result = await llm_response_node(state)

        assert result["status"] == ExecutionStatus.COMPLETE
        assert result["selected_model"] == "gpt-4o"
        assert result["final_response"]["type"] == "llm_response"
        assert "Keycloak token exchange" in result["final_response"]["answer"]

    @pytest.mark.asyncio
    async def test_preserves_context_package_without_runtime_services(self) -> None:
        state = _make_state()

        result = await llm_response_node(state)

        assert result["status"] == ExecutionStatus.COMPLETE
        assert result["final_response"]["type"] == "context_package"

    @pytest.mark.asyncio
    async def test_attaches_invocation_error_when_chain_exhausted(self) -> None:
        runtime = SimpleNamespace(
            fallback_invoker=MagicMock(),
            get_model_definition=AsyncMock(
                return_value=SimpleNamespace(latency_tier=LatencyTier.MEDIUM)
            ),
        )
        runtime.fallback_invoker.invoke = AsyncMock(
            return_value=InvocationFailure(
                message="All candidates failed.",
                attempts=2,
                last_error_code="timeout",
                tried_model_ids=["gpt-4o", "gpt-4o-mini"],
            )
        )
        state = _make_state(_config={"routing_runtime": runtime})

        result = await llm_response_node(state)

        assert result["status"] == ExecutionStatus.COMPLETE
        assert result["final_response"]["type"] == "context_package"
        assert result["final_response"]["invocation_error"] == "All candidates failed."