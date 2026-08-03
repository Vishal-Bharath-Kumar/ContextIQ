"""Shared pytest fixtures for the clarification round-trip integration tests — TASK-US011-05.

Provides all mock fixtures needed to exercise the full clarification round-trip
without making any live LLM or Kafka calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import src.gateway.tools.clarification_reply as _cr_module
from src.agents.graph import build_graph
from src.agents.state import ExecutionStatus

# ---------------------------------------------------------------------------
# Intent-chain mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_intent_chain(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the intent LLM chain to return low-confidence general classification."""
    chain = AsyncMock()
    chain.ainvoke = AsyncMock(
        return_value={
            "intent_type": "general",
            "confidence": 0.4,
            "reasoning": "Prompt is too ambiguous to classify with confidence.",
        }
    )
    monkeypatch.setattr("src.agents.nodes.intent._chain", chain)
    return chain


@pytest.fixture
def mock_intent_chain_high_confidence(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the intent LLM chain to return high-confidence debugging classification."""
    chain = AsyncMock()
    chain.ainvoke = AsyncMock(
        return_value={
            "intent_type": "debugging",
            "confidence": 0.82,
            "reasoning": "Clear debugging intent identified.",
        }
    )
    monkeypatch.setattr("src.agents.nodes.intent._chain", chain)
    return chain


@pytest.fixture
def mock_intent_chain_always_low(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the intent LLM chain to always return sub-threshold confidence."""
    chain = AsyncMock()
    chain.ainvoke = AsyncMock(
        return_value={
            "intent_type": "general",
            "confidence": 0.3,
            "reasoning": "Intent remains unclear after clarification.",
        }
    )
    monkeypatch.setattr("src.agents.nodes.intent._chain", chain)
    return chain


class _CapturingChain:
    """Intent-chain stub that records the last prompt text it received."""

    def __init__(self) -> None:
        self.last_prompt: str | None = None

    async def ainvoke(self, inputs: dict) -> dict:
        self.last_prompt = inputs.get("prompt_text", "")
        return {
            "intent_type": "debugging",
            "confidence": 0.82,
            "reasoning": "Captured during test — high confidence.",
        }


@pytest.fixture
def mock_intent_chain_capture(monkeypatch: pytest.MonkeyPatch) -> _CapturingChain:
    """Patch the intent LLM chain with a capturing stub that records the prompt."""
    chain = _CapturingChain()
    monkeypatch.setattr("src.agents.nodes.intent._chain", chain)
    return chain


# ---------------------------------------------------------------------------
# Clarification-chain mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_clar_chain(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the clarification LLM chain to return a deterministic question."""
    chain = AsyncMock()
    chain.ainvoke = AsyncMock(
        return_value="What specific service are you referring to?"
    )
    monkeypatch.setattr("src.agents.nodes.clarification_node._clar_chain", chain)
    return chain


# ---------------------------------------------------------------------------
# Kafka publisher (no-op — tests build graphs without a publisher)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kafka_publisher() -> None:
    """No-op fixture: integration tests build graphs without a Kafka publisher."""
    return None


# ---------------------------------------------------------------------------
# Retrieval-node mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_retrieval_node(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the retrieval_node name imported in graph.py so build_graph() picks it up.

    Must be set up before build_graph() is called (guaranteed by fixture
    dependency ordering when used as a parameter of mock_checkpointer_with_round_1).
    """
    mock = AsyncMock(
        return_value={
            "raw_context": [],
            "ranked_context": [],
            "degraded_sources": [],
            "status": ExecutionStatus.RUNNING,
            "current_node": "retrieval_agent",
        }
    )
    monkeypatch.setattr("src.agents.graph.retrieval_node", mock)
    return mock


# ---------------------------------------------------------------------------
# Prior-state snapshot builder
# ---------------------------------------------------------------------------


def _make_prior_snapshot(
    *,
    clarification_round: int = 0,
    session_id: str = "sess-001",
) -> MagicMock:
    """Return a fake LangGraph StateSnapshot for a completed clarification turn."""
    snapshot = MagicMock()
    snapshot.values = {
        "request_id": session_id,
        "user_id": "test-user",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "context_search",
        "prompt": "Fix it",
        "timestamp": "2026-07-16T00:00:00Z",
        "status": ExecutionStatus.COMPLETE,
        "current_node": "clarification_response",
        "error": None,
        "intent_type": "general",
        "intent_confidence": 0.4,
        "intent_source_list": None,
        "execution_plan": None,
        "requires_clarification": True,
        "clarification_question": "What specific service are you referring to?",
        "clarification_round": clarification_round,
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
    return snapshot


# ---------------------------------------------------------------------------
# Checkpointer / graph fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_checkpointer_with_state(monkeypatch: pytest.MonkeyPatch) -> object:
    """Build a real graph and seed aget_state with a clarification_round=0 prior state.

    The graph is registered via the module-level _graph attribute so that
    invoke_clarification_reply can retrieve it via _get_graph().
    """
    graph = build_graph()
    graph.aget_state = AsyncMock(
        return_value=_make_prior_snapshot(clarification_round=0, session_id="sess-001")
    )
    monkeypatch.setattr(_cr_module, "_graph", graph)
    return graph


@pytest.fixture
def mock_checkpointer_with_round_1(
    monkeypatch: pytest.MonkeyPatch,
    mock_retrieval_node: AsyncMock,
) -> object:
    """Build a real graph (with retrieval patched) seeded with clarification_round=1.

    Depends on mock_retrieval_node so pytest sets it up first, ensuring
    build_graph() captures the patched retrieval_node name.
    """
    graph = build_graph()
    graph.aget_state = AsyncMock(
        return_value=_make_prior_snapshot(clarification_round=1, session_id="sess-002")
    )
    monkeypatch.setattr(_cr_module, "_graph", graph)
    return graph


@pytest.fixture
def mock_checkpointer_empty(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Provide a graph whose aget_state returns None, simulating an expired session."""
    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=None)
    monkeypatch.setattr(_cr_module, "_graph", graph)
    return graph
