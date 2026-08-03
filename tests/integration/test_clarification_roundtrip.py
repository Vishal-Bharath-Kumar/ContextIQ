"""End-to-end clarification round-trip integration tests — TASK-US011-05.

Exercises the full clarification round-trip from ambiguous prompt submission
to second-pass plan generation.  All LLM chains and Kafka publishers are
mocked — no live external calls are made.

Test suite:
    test_ambiguous_prompt_returns_clarification_needed
    test_clarification_reply_produces_execution_plan
    test_second_low_confidence_forced_to_retrieval
    test_expired_session_returns_mcp_error
    test_merged_prompt_passed_to_second_pass_intent_node

Run:
    pytest tests/integration/test_clarification_roundtrip.py -v
    pytest tests/integration/test_clarification_roundtrip.py --asyncio-mode=auto
"""
from __future__ import annotations

from typing import Protocol
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS, ErrorData

import src.gateway.tools.clarification_reply as _cr_module
from src.agents.graph import build_graph
from src.agents.planning.prompt_merger import merge_prompt
from src.agents.state import ExecutionStatus


class _HasLastPrompt(Protocol):
    """Structural protocol for the capturing intent-chain stub."""

    last_prompt: str | None

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _serialize(obj: object) -> object:
    """Recursively convert Pydantic models to plain dicts for assertion convenience."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


async def invoke_pipeline(prompt: str, session_id: str) -> dict:
    """Build a fresh graph and run the first-pass pipeline.

    Returns the ``final_response`` dict from the terminal AgentState, with
    Pydantic models serialized to plain dicts for easy assertion.
    """
    graph = build_graph()
    initial_state: dict = {
        "request_id": session_id,
        "user_id": "test-user",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "context_search",
        "prompt": prompt,
        "timestamp": "2026-07-16T00:00:00Z",
        "status": ExecutionStatus.PENDING,
        "current_node": "",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
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
    result = await graph.ainvoke(initial_state)
    return _serialize(result.get("final_response") or {})


async def invoke_clarification_reply(session_id: str, clarification: str) -> dict:
    """Resume the pipeline after a clarification answer.

    Mirrors the ``clarification_reply`` MCP tool logic but returns the full
    serialized AgentState dict (Pydantic models converted to plain dicts) so
    tests can assert directly on ``execution_plan``, ``clarification_round``,
    and other state fields.

    Raises:
        McpError: with code ``INVALID_PARAMS`` when the session is not found
                  or has expired (i.e. ``aget_state`` returns ``None``).
    """
    graph = _cr_module._get_graph()

    prior_state = await graph.aget_state(
        config={"configurable": {"thread_id": session_id}}
    )
    if prior_state is None:
        raise McpError(
            ErrorData(
                code=INVALID_PARAMS,
                message=f"Session '{session_id}' not found or expired",
            )
        )

    values = prior_state.values
    merged = merge_prompt(
        original_prompt=values["prompt"],
        clarification_question=values["clarification_question"],
        user_clarification=clarification,
    )

    # Include identity fields so the node-logging wrapper (which reads
    # state["request_id"] and state["user_id"]) does not KeyError.
    # In production a Redis checkpointer restores these automatically;
    # here we carry them forward from the prior-state snapshot.
    resume_state: dict = {
        "request_id": values["request_id"],
        "user_id": values["user_id"],
        "username": values["username"],
        "roles": values["roles"],
        "tool_name": values["tool_name"],
        "timestamp": values["timestamp"],
        "prompt": merged,
        "clarification_round": 1,
        "requires_clarification": False,
        "status": ExecutionStatus.PENDING,
        "intent_type": None,
        "intent_confidence": None,
        "intent_source_list": None,
        "execution_plan": None,
    }

    result = await graph.ainvoke(
        resume_state,
        config={"configurable": {"thread_id": session_id}},
    )
    return _serialize(result)


# ---------------------------------------------------------------------------
# Test 1 — Ambiguous prompt returns clarification_needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ambiguous_prompt_returns_clarification_needed(
    mock_intent_chain: AsyncMock,
    mock_clar_chain: AsyncMock,
    mock_kafka_publisher: None,
) -> None:
    """Low-confidence first pass must route to clarification and return the MCP shape."""
    response = await invoke_pipeline(prompt="Fix it", session_id="sess-001")

    assert response["type"] == "clarification_needed"
    assert response["question"].endswith("?")
    assert len(response["question"].split()) <= 50
    assert response["session_id"] == "sess-001"
    assert response["clarification_round"] == 0


# ---------------------------------------------------------------------------
# Test 2 — Clarification reply produces an execution plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarification_reply_produces_execution_plan(
    mock_intent_chain_high_confidence: AsyncMock,
    mock_clar_chain: AsyncMock,
    mock_checkpointer_with_state: object,
    mock_kafka_publisher: None,
) -> None:
    """High-confidence second pass must set execution_plan with debugging sources."""
    result = await invoke_clarification_reply(
        session_id="sess-001",
        clarification="The auth service throwing 401 on valid tokens in production",
    )

    assert result.get("execution_plan") is not None
    plan = result["execution_plan"]
    assert plan["sources"] == ["github", "stackoverflow", "jira"]
    assert plan["ranking_strategy"] == "hybrid"
    assert result.get("clarification_round") == 1


# ---------------------------------------------------------------------------
# Test 3 — Second low-confidence is forced to retrieval (round cap)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_low_confidence_forced_to_retrieval(
    mock_intent_chain_always_low: AsyncMock,
    mock_checkpointer_with_round_1: object,
    mock_retrieval_node: AsyncMock,
    mock_kafka_publisher: None,
) -> None:
    """When clarification_round >= MAX_CLARIFICATION_ROUNDS, retrieval must run unconditionally."""
    result = await invoke_clarification_reply(
        session_id="sess-002",
        clarification="Still unclear",
    )

    # Retrieval was reached (not a second clarification)
    assert mock_retrieval_node.called
    assert result.get("requires_clarification") is not True


# ---------------------------------------------------------------------------
# Test 4 — Expired session returns McpError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_session_returns_mcp_error(mock_checkpointer_empty: MagicMock) -> None:
    """aget_state returning None must raise McpError with INVALID_PARAMS."""
    with pytest.raises(McpError) as exc_info:
        await invoke_clarification_reply(
            session_id="sess-expired",
            clarification="Some answer",
        )
    assert exc_info.value.error.code == INVALID_PARAMS


# ---------------------------------------------------------------------------
# Test 5 — Merged prompt is passed to the second-pass intent classifier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merged_prompt_passed_to_second_pass_intent_node(
    mock_intent_chain_capture: _HasLastPrompt,
    mock_checkpointer_with_state: object,
    mock_kafka_publisher: None,
) -> None:
    """The merged prompt must contain all three template sections from merge_prompt()."""
    await invoke_clarification_reply(
        session_id="sess-003",
        clarification="The Kubernetes ingress controller",
    )

    captured_prompt = mock_intent_chain_capture.last_prompt
    assert captured_prompt is not None
    assert "[Original request]" in captured_prompt
    assert "[Clarification asked]" in captured_prompt
    assert "[User clarification]" in captured_prompt
    assert "The Kubernetes ingress controller" in captured_prompt
