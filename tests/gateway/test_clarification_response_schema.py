"""Unit tests for TASK-US011-02.

Covers:
- ClarificationNeededResponse Pydantic model validation (all five fields)
- tools/call handler serialises clarification exit as TextContent (not McpError)
- JSON payload round-trips correctly to ClarificationNeededResponse schema
- Happy-path result is not affected by the clarification branch
"""
from __future__ import annotations

import json
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.gateway.schemas.call_types import ToolCallOutput
from src.gateway.schemas.clarification_response import ClarificationNeededResponse

# ---------------------------------------------------------------------------
# ClarificationNeededResponse model tests
# ---------------------------------------------------------------------------


class TestClarificationNeededResponse:
    def test_validates_all_five_fields(self) -> None:
        data = {
            "type": "clarification_needed",
            "question": "Which microservice do you want to refactor?",
            "original_prompt": "refactor the service",
            "session_id": "req-123",
            "clarification_round": 1,
        }
        resp = ClarificationNeededResponse.model_validate(data)
        assert resp.type == "clarification_needed"
        assert resp.question == "Which microservice do you want to refactor?"
        assert resp.original_prompt == "refactor the service"
        assert resp.session_id == "req-123"
        assert resp.clarification_round == 1

    def test_type_literal_default(self) -> None:
        resp = ClarificationNeededResponse(
            question="What language?",
            original_prompt="write code",
            session_id="req-abc",
        )
        assert resp.type == "clarification_needed"

    def test_clarification_round_defaults_to_zero(self) -> None:
        resp = ClarificationNeededResponse(
            question="Which service?",
            original_prompt="fix the bug",
            session_id="req-xyz",
        )
        assert resp.clarification_round == 0

    def test_model_dump_json_is_valid_json(self) -> None:
        resp = ClarificationNeededResponse(
            question="Which service?",
            original_prompt="fix the bug",
            session_id="req-xyz",
            clarification_round=2,
        )
        payload = resp.model_dump_json()
        parsed = json.loads(payload)
        assert parsed["type"] == "clarification_needed"
        assert parsed["session_id"] == "req-xyz"
        assert parsed["clarification_round"] == 2

    def test_type_field_rejects_wrong_value(self) -> None:
        with pytest.raises(ValidationError):
            ClarificationNeededResponse.model_validate(
                {
                    "type": "error",
                    "question": "Q?",
                    "original_prompt": "p",
                    "session_id": "s",
                }
            )

    def test_roundtrip_from_clarification_node_output(self) -> None:
        """Schema accepts the exact shape written by clarification_node."""
        node_output = {
            "type": "clarification_needed",
            "question": "Are you targeting the auth service or the gateway?",
            "original_prompt": "add logging to the service",
            "session_id": "e2e-req-001",
            "clarification_round": 0,
        }
        resp = ClarificationNeededResponse.model_validate(node_output)
        assert resp.session_id == "e2e-req-001"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_tool_def() -> MagicMock:
    tool_def = MagicMock()
    tool_def.inputSchema.model_dump.return_value = {"type": "object", "properties": {}}
    tool_def.output_schema = None
    return tool_def


def _build_handler(tool_output: dict | list | str) -> object:
    """Return the captured ``handle_tool_call`` coroutine using a mock FastMCP.

    Uses the same decorator-capture pattern as
    tests/unit/gateway/test_tools_call_handler.py so tests are not coupled
    to FastMCP internal APIs.
    """
    from src.gateway.handlers.tools_call import register_tools_call_handler

    mock_registry = AsyncMock()
    mock_registry.get_by_name.return_value = _make_tool_def()

    mock_client = AsyncMock()
    mock_client.execute.return_value = ToolCallOutput(
        data=tool_output,
        output_schema_version="1.0",
    )

    captured: list[object] = []

    def _call_tool_decorator() -> Callable[[object], object]:
        def _inner(fn: object) -> object:
            captured.append(fn)
            return fn
        return _inner

    mock_mcp = MagicMock()
    mock_mcp.call_tool = _call_tool_decorator

    register_tools_call_handler(mock_mcp, registry=mock_registry, agent_client=mock_client)
    assert captured, "register_tools_call_handler did not invoke mcp.call_tool()"
    return captured[0]


# ---------------------------------------------------------------------------
# tools/call handler serialisation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestToolsCallClarificationPath:
    async def test_clarification_exit_returns_text_content(self) -> None:
        """Handler must return a TextContent list for a clarification exit."""
        from mcp.types import TextContent

        clarification_data = {
            "type": "clarification_needed",
            "question": "Which database are you referring to?",
            "original_prompt": "migrate the database",
            "session_id": "req-session-42",
            "clarification_round": 0,
        }
        handler = _build_handler(clarification_data)

        with patch("src.gateway.handlers.tools_call.get_request_context") as mock_ctx:
            mock_ctx.return_value = MagicMock(
                request_id="req-session-42", user_id="user-1", trace_id=0
            )
            result = await handler("test_tool", {})

        assert len(result) == 1
        tc = result[0]
        assert isinstance(tc, TextContent)
        assert tc.type == "text"
        parsed = json.loads(tc.text)
        assert parsed["type"] == "clarification_needed"
        assert parsed["session_id"] == "req-session-42"

    async def test_text_content_json_deserialises_to_schema(self) -> None:
        """TextContent.text must round-trip to ClarificationNeededResponse."""
        clarification_data = {
            "type": "clarification_needed",
            "question": "Which service do you mean?",
            "original_prompt": "update the config",
            "session_id": "req-99",
            "clarification_round": 1,
        }
        handler = _build_handler(clarification_data)

        with patch("src.gateway.handlers.tools_call.get_request_context") as mock_ctx:
            mock_ctx.return_value = MagicMock(request_id="req-99", user_id="u", trace_id=0)
            result = await handler("test_tool", {})

        parsed = json.loads(result[0].text)
        clar = ClarificationNeededResponse.model_validate(parsed)
        assert clar.type == "clarification_needed"
        assert clar.session_id == "req-99"
        assert clar.clarification_round == 1

    async def test_happy_path_unaffected_by_clarification_branch(self) -> None:
        """Non-clarification results continue to be serialised with json.dumps."""
        normal_data = {"answer": "42", "sources": []}
        handler = _build_handler(normal_data)

        with patch("src.gateway.handlers.tools_call.get_request_context") as mock_ctx:
            mock_ctx.return_value = MagicMock(request_id="req-00", user_id="u", trace_id=0)
            result = await handler("test_tool", {})

        parsed = json.loads(result[0].text)
        assert parsed == normal_data

    async def test_no_mcp_error_raised_on_clarification_exit(self) -> None:
        """McpError must NOT be raised for clarification exits."""
        from mcp.shared.exceptions import McpError

        clarification_data = {
            "type": "clarification_needed",
            "question": "Q?",
            "original_prompt": "p",
            "session_id": "s",
            "clarification_round": 0,
        }
        handler = _build_handler(clarification_data)

        with patch("src.gateway.handlers.tools_call.get_request_context") as mock_ctx:
            mock_ctx.return_value = MagicMock(request_id="s", user_id="u", trace_id=0)
            try:
                await handler("test_tool", {})
            except McpError:
                pytest.fail("McpError raised for clarification exit — must not raise")
