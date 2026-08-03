"""Unit tests for TASK-US011-04 — clarification_reply MCP tool.

Covers:
- ClarificationReplyInput schema validation (valid, min_length, max_length)
- merge_prompt() output structure (normal, whitespace trimming, max-length clarification)
- clarification_reply tool: happy path resumes pipeline with merged prompt
- clarification_reply tool: expired/unknown session_id raises McpError(INVALID_PARAMS)
- clarification_reply tool: clarification_round == 1 in resume state patch
- register_clarification_reply_tool() registers the tool on FastMCP
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS
from pydantic import ValidationError

from src.agents.planning.prompt_merger import MERGE_TEMPLATE, merge_prompt
from src.gateway.schemas.clarification_reply import ClarificationReplyInput

# ---------------------------------------------------------------------------
# ClarificationReplyInput schema
# ---------------------------------------------------------------------------


class TestClarificationReplyInput:
    def test_valid_input(self) -> None:
        obj = ClarificationReplyInput(
            session_id="sess-001",
            clarification="I meant the auth service.",
        )
        assert obj.session_id == "sess-001"
        assert obj.clarification == "I meant the auth service."

    def test_clarification_min_length_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            ClarificationReplyInput(session_id="sess-001", clarification="")

    def test_clarification_max_length_rejects_oversized(self) -> None:
        with pytest.raises(ValidationError):
            ClarificationReplyInput(session_id="sess-001", clarification="x" * 2_001)

    def test_clarification_max_length_accepts_boundary(self) -> None:
        obj = ClarificationReplyInput(
            session_id="sess-001",
            clarification="x" * 2_000,
        )
        assert len(obj.clarification) == 2_000


# ---------------------------------------------------------------------------
# merge_prompt()
# ---------------------------------------------------------------------------


class TestMergePrompt:
    def test_normal_case_contains_all_three_sections(self) -> None:
        result = merge_prompt(
            original_prompt="fix the auth service",
            clarification_question="Which auth service do you mean?",
            user_clarification="The JWT validation service.",
        )
        assert "[Original request]" in result
        assert "fix the auth service" in result
        assert "[Clarification asked]" in result
        assert "Which auth service do you mean?" in result
        assert "[User clarification]" in result
        assert "The JWT validation service." in result

    def test_whitespace_trimming(self) -> None:
        result = merge_prompt(
            original_prompt="  refactor service  ",
            clarification_question="  Which one?  ",
            user_clarification="  The gateway.  ",
        )
        assert "refactor service" in result
        assert "  refactor service  " not in result
        assert "Which one?" in result
        assert "The gateway." in result

    def test_max_length_clarification_is_included(self) -> None:
        long_clarification = "a" * 2_000
        result = merge_prompt(
            original_prompt="do something",
            clarification_question="What exactly?",
            user_clarification=long_clarification,
        )
        assert long_clarification in result

    def test_output_matches_template_structure(self) -> None:
        expected = MERGE_TEMPLATE.format(
            original_prompt="do something",
            clarification_question="What exactly?",
            user_clarification="Everything.",
        )
        result = merge_prompt(
            original_prompt="do something",
            clarification_question="What exactly?",
            user_clarification="Everything.",
        )
        assert result == expected


# ---------------------------------------------------------------------------
# clarification_reply tool (via register_clarification_reply_tool)
# ---------------------------------------------------------------------------


def _build_mock_graph(prior_values: dict | None) -> MagicMock:
    """Return a mock CompiledStateGraph with configurable prior state."""
    graph = MagicMock()
    if prior_values is None:
        graph.aget_state = AsyncMock(return_value=None)
    else:
        mock_state = MagicMock()
        mock_state.values = prior_values
        graph.aget_state = AsyncMock(return_value=mock_state)
    graph.ainvoke = AsyncMock(
        return_value={"final_response": {"answer": "Done", "sources": []}}
    )
    return graph


def _capture_tool(graph: MagicMock) -> object:
    """Register the tool on a minimal FastMCP stub and return the callable."""
    import src.gateway.tools.clarification_reply as _mod

    tools: dict = {}

    class _FakeMCP:
        def tool(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
                tools[fn.__name__] = fn
                return fn
            return _decorator

    _mod._graph = graph  # inject the graph
    _mod.register_clarification_reply_tool(_FakeMCP())  # type: ignore[arg-type]
    return tools["clarification_reply"]


@pytest.mark.asyncio
class TestClarificationReplyTool:
    async def test_happy_path_returns_text_content(self) -> None:
        prior_values = {
            "prompt": "refactor the service",
            "clarification_question": "Which service?",
        }
        graph = _build_mock_graph(prior_values)
        fn = _capture_tool(graph)

        result = await fn(session_id="sess-abc", clarification="The gateway service.")

        assert len(result) == 1
        assert result[0].type == "text"
        payload = json.loads(result[0].text)
        assert payload == {"answer": "Done", "sources": []}

    async def test_happy_path_passes_merged_prompt_to_ainvoke(self) -> None:
        prior_values = {
            "prompt": "original prompt",
            "clarification_question": "What do you mean?",
        }
        graph = _build_mock_graph(prior_values)
        fn = _capture_tool(graph)

        await fn(session_id="sess-abc", clarification="I mean the API layer.")

        call_args = graph.ainvoke.call_args
        resume_state = call_args[0][0]
        assert "[Original request]" in resume_state["prompt"]
        assert "original prompt" in resume_state["prompt"]
        assert "[User clarification]" in resume_state["prompt"]
        assert "I mean the API layer." in resume_state["prompt"]

    async def test_clarification_round_is_one_in_resume_state(self) -> None:
        prior_values = {
            "prompt": "do something",
            "clarification_question": "What exactly?",
        }
        graph = _build_mock_graph(prior_values)
        fn = _capture_tool(graph)

        await fn(session_id="sess-abc", clarification="Everything.")

        resume_state = graph.ainvoke.call_args[0][0]
        assert resume_state["clarification_round"] == 1

    async def test_resume_state_requires_clarification_is_false(self) -> None:
        prior_values = {
            "prompt": "do something",
            "clarification_question": "What exactly?",
        }
        graph = _build_mock_graph(prior_values)
        fn = _capture_tool(graph)

        await fn(session_id="sess-abc", clarification="Everything.")

        resume_state = graph.ainvoke.call_args[0][0]
        assert resume_state["requires_clarification"] is False

    async def test_resume_state_resets_intent_fields(self) -> None:
        prior_values = {
            "prompt": "do something",
            "clarification_question": "What exactly?",
        }
        graph = _build_mock_graph(prior_values)
        fn = _capture_tool(graph)

        await fn(session_id="sess-abc", clarification="Everything.")

        resume_state = graph.ainvoke.call_args[0][0]
        for field in ("intent_type", "intent_confidence", "intent_source_list", "execution_plan"):
            assert resume_state[field] is None

    async def test_expired_session_raises_mcp_error_invalid_params(self) -> None:
        graph = _build_mock_graph(prior_values=None)
        fn = _capture_tool(graph)

        with pytest.raises(McpError) as exc_info:
            await fn(session_id="expired-sess", clarification="Any answer.")

        assert exc_info.value.error.code == INVALID_PARAMS

    async def test_aget_state_called_with_thread_id(self) -> None:
        prior_values = {
            "prompt": "prompt text",
            "clarification_question": "Question?",
        }
        graph = _build_mock_graph(prior_values)
        fn = _capture_tool(graph)

        await fn(session_id="my-session-id", clarification="My answer.")

        graph.aget_state.assert_called_once_with(
            config={"configurable": {"thread_id": "my-session-id"}}
        )

    async def test_ainvoke_uses_same_thread_id(self) -> None:
        prior_values = {
            "prompt": "prompt text",
            "clarification_question": "Question?",
        }
        graph = _build_mock_graph(prior_values)
        fn = _capture_tool(graph)

        await fn(session_id="my-session-id", clarification="My answer.")

        config = graph.ainvoke.call_args[1]["config"]
        assert config["configurable"]["thread_id"] == "my-session-id"

    async def test_empty_final_response_returns_empty_object(self) -> None:
        prior_values = {
            "prompt": "prompt text",
            "clarification_question": "Question?",
        }
        graph = _build_mock_graph(prior_values)
        graph.ainvoke = AsyncMock(return_value={})
        fn = _capture_tool(graph)

        result = await fn(session_id="sess", clarification="Answer.")

        payload = json.loads(result[0].text)
        assert payload == {}
