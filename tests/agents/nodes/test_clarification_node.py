"""Unit tests for TASK-US011-01 — clarification_node() with LLM chain.

All LLM calls are mocked — no live API calls in CI.

Coverage targets:
- _enforce_word_limit(): exact-limit, over-limit, trailing punctuation
- ClarificationQuestion schema validation (max_length guard)
- clarification_node() output shape: requires_clarification, clarification_question, status
- Generated question ≤ 50 words and ends with '?'
- clarification_question populated in state patch
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from src.agents.nodes.clarification_node import (
    CLARIFICATION_SYSTEM_PROMPT,
    _enforce_word_limit,
    clarification_node,
)
from src.agents.schemas.clarification import ClarificationQuestion
from src.agents.state import AgentState, ExecutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    prompt: str = "Fix my broken thing",
    confidence: float = 0.4,
    intent_type: str = "debugging",
) -> AgentState:
    return {
        "request_id": "req-clar-test",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["user"],
        "tool_name": "search",
        "prompt": prompt,
        "timestamp": "2026-01-01T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "clarification_node",
        "error": None,
        "intent_type": intent_type,  # type: ignore[typeddict-item]
        "intent_confidence": confidence,
        "intent_source_list": None,
        "execution_plan": None,
        "requires_clarification": None,
        "clarification_question": None,
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


def _mock_chain(question: str) -> AsyncMock:
    """Return an async mock whose ``ainvoke`` returns a fixed question string."""
    chain = AsyncMock()
    chain.ainvoke = AsyncMock(return_value=question)
    return chain


# ---------------------------------------------------------------------------
# _enforce_word_limit() tests
# ---------------------------------------------------------------------------


class TestEnforceWordLimit:
    def test_short_text_unchanged(self) -> None:
        text = "Which service does this error originate from?"
        assert _enforce_word_limit(text) == text

    def test_exactly_50_words_unchanged(self) -> None:
        words = ["word"] * 50
        text = " ".join(words) + "?"
        result = _enforce_word_limit(text)
        assert len(result.split()) == 50  # "word?" is one token, total is 50
        assert result == text

    def test_51_words_truncated_to_50(self) -> None:
        words = ["word"] * 51
        text = " ".join(words)
        result = _enforce_word_limit(text)
        assert len(result.split()) == 50

    def test_truncated_result_ends_with_question_mark(self) -> None:
        words = ["word"] * 60
        text = " ".join(words)
        result = _enforce_word_limit(text)
        assert result.endswith("?")

    def test_trailing_comma_stripped_before_question_mark(self) -> None:
        words = ["word"] * 51
        words[49] = "word,"
        text = " ".join(words)
        result = _enforce_word_limit(text)
        assert not result.endswith(",?")
        assert result.endswith("?")

    def test_trailing_semicolon_stripped_before_question_mark(self) -> None:
        words = ["word"] * 51
        words[49] = "word;"
        text = " ".join(words)
        result = _enforce_word_limit(text)
        assert not result.endswith(";?")
        assert result.endswith("?")

    def test_custom_limit(self) -> None:
        words = ["w"] * 10
        text = " ".join(words)
        result = _enforce_word_limit(text, limit=5)
        assert len(result.split()) == 5
        assert result.endswith("?")


# ---------------------------------------------------------------------------
# ClarificationQuestion schema tests
# ---------------------------------------------------------------------------


class TestClarificationQuestionSchema:
    def test_valid_question_accepted(self) -> None:
        q = ClarificationQuestion(question="Are you debugging a Python or Go service?")
        assert q.question == "Are you debugging a Python or Go service?"

    def test_max_length_300_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ClarificationQuestion(question="x" * 301)

    def test_empty_string_accepted_by_pydantic(self) -> None:
        # Pydantic does not enforce min_length unless specified — just document behaviour
        q = ClarificationQuestion(question="")
        assert q.question == ""

    def test_question_at_300_chars_accepted(self) -> None:
        q = ClarificationQuestion(question="a" * 300)
        assert len(q.question) == 300


# ---------------------------------------------------------------------------
# clarification_node() output shape
# ---------------------------------------------------------------------------


class TestClarificationNodeOutput:
    @pytest.mark.asyncio
    async def test_requires_clarification_is_true(self) -> None:
        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=_mock_chain("Which component is failing?"),
        ):
            result = await clarification_node(_make_state())

        assert result["requires_clarification"] is True

    @pytest.mark.asyncio
    async def test_status_is_complete(self) -> None:
        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=_mock_chain("Which component is failing?"),
        ):
            result = await clarification_node(_make_state())

        assert result["status"] == ExecutionStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_clarification_question_in_patch(self) -> None:
        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=_mock_chain("Which component is failing?"),
        ):
            result = await clarification_node(_make_state())

        assert "clarification_question" in result
        assert result["clarification_question"] == "Which component is failing?"

    @pytest.mark.asyncio
    async def test_question_stripped_of_whitespace(self) -> None:
        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=_mock_chain("  Which component is failing?  "),
        ):
            result = await clarification_node(_make_state())

        assert result["clarification_question"] == "Which component is failing?"

    @pytest.mark.asyncio
    async def test_question_ends_with_question_mark(self) -> None:
        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=_mock_chain("Which service owns this endpoint?"),
        ):
            result = await clarification_node(_make_state())

        assert result["clarification_question"].endswith("?")

    @pytest.mark.asyncio
    async def test_question_at_most_50_words(self) -> None:
        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=_mock_chain("Which service owns this endpoint?"),
        ):
            result = await clarification_node(_make_state())

        word_count = len(result["clarification_question"].split())
        assert word_count <= 50

    @pytest.mark.asyncio
    async def test_over_limit_response_truncated(self) -> None:
        long_question = " ".join(["word"] * 60) + "?"
        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=_mock_chain(long_question),
        ):
            result = await clarification_node(_make_state())

        assert len(result["clarification_question"].split()) <= 50
        assert result["clarification_question"].endswith("?")

    @pytest.mark.asyncio
    async def test_unknown_intent_used_when_intent_type_missing(self) -> None:
        state = _make_state()
        state["intent_type"] = None  # type: ignore[typeddict-item]

        invocation_args: list[dict] = []

        async def capture_invoke(kwargs: dict) -> str:
            invocation_args.append(kwargs)
            return "Could you clarify which service you mean?"

        mock_chain = AsyncMock()
        mock_chain.ainvoke = capture_invoke

        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=mock_chain,
        ):
            await clarification_node(state)

        assert invocation_args[0]["intent_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_confidence_forwarded_to_chain(self) -> None:
        invocation_args: list[dict] = []

        async def capture_invoke(kwargs: dict) -> str:
            invocation_args.append(kwargs)
            return "What exactly are you trying to fix?"

        mock_chain = AsyncMock()
        mock_chain.ainvoke = capture_invoke

        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=mock_chain,
        ):
            await clarification_node(_make_state(confidence=0.35))

        assert invocation_args[0]["confidence"] == pytest.approx(0.35)

    @pytest.mark.asyncio
    async def test_user_prompt_forwarded_to_chain(self) -> None:
        invocation_args: list[dict] = []

        async def capture_invoke(kwargs: dict) -> str:
            invocation_args.append(kwargs)
            return "What service are you debugging?"

        mock_chain = AsyncMock()
        mock_chain.ainvoke = capture_invoke

        with patch(
            "src.agents.nodes.clarification_node._get_clar_chain",
            return_value=mock_chain,
        ):
            await clarification_node(_make_state(prompt="my thing is broken"))

        assert invocation_args[0]["user_prompt"] == "my thing is broken"


# ---------------------------------------------------------------------------
# System prompt sanity check
# ---------------------------------------------------------------------------


class TestClarificationSystemPrompt:
    def test_prompt_contains_intent_type_placeholder(self) -> None:
        assert "{intent_type}" in CLARIFICATION_SYSTEM_PROMPT

    def test_prompt_contains_confidence_placeholder(self) -> None:
        assert "{confidence" in CLARIFICATION_SYSTEM_PROMPT

    def test_prompt_enforces_single_question_rule(self) -> None:
        assert "exactly one question" in CLARIFICATION_SYSTEM_PROMPT
