"""
Unit tests for TASK-US003-01: MCP ``tools/call`` handler.

Coverage targets (≥ 90% on handlers/tools_call.py):
  - Valid tool call: dispatches to Agent Worker and returns TextContent
  - Unknown tool name: raises McpError(INVALID_PARAMS)
  - Schema validation failure: raises McpError(INVALID_PARAMS) with message
  - Missing required argument: raises McpError(INVALID_PARAMS)
  - request_id is unique UUID v4 per invocation
  - trace_id propagated into dispatch payload
  - register_tools_call_handler wires into FastMCP correctly
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from src.gateway.clients.agent_worker_client import AgentWorkerClient
from src.gateway.context.request_context import RequestContext
from src.gateway.handlers.tools_call import register_tools_call_handler, set_user_id_context
from src.gateway.schemas.call_types import ToolCallDispatch, ToolCallOutput, ToolCallResponse
from src.gateway.schemas.tool_types import InputSchema, ToolDefinition, ToolListResult
from src.gateway.services.tool_registry import ToolRegistryService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _make_tool(
    name: str,
    properties: dict | None = None,
    required: list[str] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Description of {name}.",
        inputSchema=InputSchema(
            properties=properties or {"query": {"type": "string"}},
            required=required or ["query"],
        ),
    )


def _make_registry(tools: list[ToolDefinition]) -> ToolRegistryService:
    registry = MagicMock(spec=ToolRegistryService)
    registry.get_active_tools = AsyncMock(return_value=ToolListResult(tools=tools))

    async def _get_by_name(name: str) -> ToolDefinition | None:
        return next((t for t in tools if t.name == name), None)

    registry.get_by_name = AsyncMock(side_effect=_get_by_name)
    return registry


def _make_agent_client(output: object = "done") -> AgentWorkerClient:
    client = MagicMock(spec=AgentWorkerClient)

    async def _execute(dispatch: ToolCallDispatch) -> ToolCallOutput:
        return ToolCallOutput(data=output if isinstance(output, (dict, list, str)) else str(output))

    client.execute = AsyncMock(side_effect=_execute)
    return client


def _build_handler(
    tools: list[ToolDefinition],
    agent_output: object = "done",
) -> tuple[object, ToolRegistryService, AgentWorkerClient]:
    """Return (handler_coroutine, registry_mock, client_mock) for isolated tests."""
    registry = _make_registry(tools)
    agent_client = _make_agent_client(agent_output)

    captured: list[object] = []

    def _call_tool_decorator() -> Callable[[object], object]:
        def _inner(fn: object) -> object:
            captured.append(fn)
            return fn
        return _inner

    mock_mcp = MagicMock()
    mock_mcp.call_tool = _call_tool_decorator

    register_tools_call_handler(mock_mcp, registry=registry, agent_client=agent_client)
    assert captured, "No handler was registered via @mcp.call_tool()"
    return captured[0], registry, agent_client


# ---------------------------------------------------------------------------
# ToolCallDispatch / ToolCallResponse schema tests
# ---------------------------------------------------------------------------

class TestCallTypes:
    def test_dispatch_requires_all_fields(self) -> None:
        dispatch = ToolCallDispatch(
            request_id="req-1",
            user_id="user-abc",
            tool_name="search",
            arguments={"query": "hello"},
            trace_id="0" * 32,
        )
        assert dispatch.tool_name == "search"
        assert dispatch.arguments == {"query": "hello"}

    def test_response_model_validates(self) -> None:
        resp = ToolCallResponse(request_id="req-1", output={"key": "value"})
        assert resp.output == {"key": "value"}

    def test_response_output_accepts_primitives(self) -> None:
        for value in [42, "text", True, None, [1, 2]]:
            resp = ToolCallResponse(request_id="r", output=value)
            assert resp.output == value


# ---------------------------------------------------------------------------
# handle_tool_call — valid invocation
# ---------------------------------------------------------------------------

class TestHandleToolCallValid:
    @pytest.mark.asyncio
    async def test_returns_text_content_list(self) -> None:
        handler, _, _ = _build_handler([_make_tool("search")])
        result = await handler("search", {"query": "hello"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].type == "text"

    @pytest.mark.asyncio
    async def test_output_is_json_serialised(self) -> None:
        handler, _, _ = _build_handler([_make_tool("search")], agent_output={"answer": 42})
        result = await handler("search", {"query": "test"})
        parsed = json.loads(result[0].text)
        assert parsed == {"answer": 42}

    @pytest.mark.asyncio
    async def test_agent_client_execute_called_once(self) -> None:
        handler, _, client = _build_handler([_make_tool("search")])
        await handler("search", {"query": "hello"})
        client.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_tool_name_matches_request(self) -> None:
        handler, _, client = _build_handler([_make_tool("search")])
        await handler("search", {"query": "hello"})
        dispatch: ToolCallDispatch = client.execute.call_args[0][0]
        assert dispatch.tool_name == "search"

    @pytest.mark.asyncio
    async def test_dispatch_arguments_matches_input(self) -> None:
        handler, _, client = _build_handler([_make_tool("search")])
        await handler("search", {"query": "hello world"})
        dispatch: ToolCallDispatch = client.execute.call_args[0][0]
        assert dispatch.arguments == {"query": "hello world"}

    @pytest.mark.asyncio
    async def test_dispatch_request_id_is_uuid4(self) -> None:
        handler, _, client = _build_handler([_make_tool("search")])
        await handler("search", {"query": "test"})
        dispatch: ToolCallDispatch = client.execute.call_args[0][0]
        assert _UUID4_RE.match(dispatch.request_id), f"Not a UUID v4: {dispatch.request_id}"

    @pytest.mark.asyncio
    async def test_request_ids_are_unique_per_invocation(self) -> None:
        handler, _, client = _build_handler([_make_tool("search")])
        await handler("search", {"query": "a"})
        await handler("search", {"query": "b"})
        calls = client.execute.call_args_list
        id1 = calls[0][0][0].request_id
        id2 = calls[1][0][0].request_id
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_user_id_from_context_var(self) -> None:
        set_user_id_context("user-xyz")
        handler, _, client = _build_handler([_make_tool("search")])
        await handler("search", {"query": "q"})
        dispatch: ToolCallDispatch = client.execute.call_args[0][0]
        assert dispatch.user_id == "user-xyz"

    @pytest.mark.asyncio
    async def test_optional_argument_accepted(self) -> None:
        tool = _make_tool(
            "flexible",
            properties={"q": {"type": "string"}, "limit": {"type": "integer"}},
            required=["q"],
        )
        handler, _, _ = _build_handler([tool])
        # limit is optional — should not raise
        result = await handler("flexible", {"q": "hello"})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_info_log_emitted_for_tool_call(self) -> None:
        handler, _, _ = _build_handler([_make_tool("search")])
        ctx = RequestContext(
            request_id="123e4567-e89b-42d3-a456-426614174000",
            user_id="log-user",
            username="logger",
            roles=frozenset(),
            session_id="sess-123",
            trace_id=0,
        )

        with patch("src.gateway.handlers.tools_call.runtime_logger.info") as mock_info:
            with patch("src.gateway.handlers.tools_call.get_request_context", return_value=ctx):
                await handler("search", {"query": "hello"})

        call_args = mock_info.call_args[0]
        assert call_args[0] == "tools/call received: tool=%s request_id=%s session_id=%s user_id=%s execution=%s"
        assert call_args[1] == "search"
        assert call_args[2] == "123e4567-e89b-42d3-a456-426614174000"
        assert call_args[3] == "sess-123"
        assert call_args[4] == "log-user"
        assert call_args[5] == "agent_worker"


class TestHandleToolCallBuiltinFallback:
    @pytest.mark.asyncio
    async def test_builtin_tool_called_when_registry_misses(self) -> None:
        registry = _make_registry([])
        agent_client = _make_agent_client()
        captured: list[object] = []

        def _call_tool_decorator() -> Callable[[object], object]:
            def _inner(fn: object) -> object:
                captured.append(fn)
                return fn
            return _inner

        builtin_tool = MagicMock()
        builtin_tool.name = "builtin_search"
        builtin_tool.description = "Built-in search"
        builtin_tool.parameters = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        builtin_tool.run = AsyncMock(
            return_value=MagicMock(
                content=[TextContent(type="text", text='{"source":"builtin"}')],
                structured_content={"source": "builtin"},
            )
        )

        mock_mcp = MagicMock()
        mock_mcp.call_tool = _call_tool_decorator
        mock_mcp.get_tool = AsyncMock(return_value=builtin_tool)

        register_tools_call_handler(mock_mcp, registry=registry, agent_client=agent_client)
        handler = captured[0]

        result = await handler("builtin_search", {"query": "hello"})

        builtin_tool.run.assert_awaited_once_with({"query": "hello"})
        agent_client.execute.assert_not_called()
        assert result[0].text == '{"source":"builtin"}'

    @pytest.mark.asyncio
    async def test_builtin_tool_schedules_replay_trace(self) -> None:
        registry = _make_registry([])
        agent_client = _make_agent_client()
        captured: list[object] = []

        def _call_tool_decorator() -> Callable[[object], object]:
            def _inner(fn: object) -> object:
                captured.append(fn)
                return fn
            return _inner

        builtin_tool = MagicMock()
        builtin_tool.name = "builtin_search"
        builtin_tool.description = "Built-in search"
        builtin_tool.parameters = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        builtin_tool.run = AsyncMock(
            return_value=MagicMock(
                content=[TextContent(type="text", text='{"source":"builtin"}')],
                structured_content={"source": "builtin"},
            )
        )

        mock_mcp = MagicMock()
        mock_mcp.call_tool = _call_tool_decorator
        mock_mcp.get_tool = AsyncMock(return_value=builtin_tool)

        register_tools_call_handler(mock_mcp, registry=registry, agent_client=agent_client)
        handler = captured[0]

        with patch("src.gateway.handlers.tools_call._schedule_builtin_tool_trace") as mock_schedule:
            await handler("builtin_search", {"query": "hello"})

        mock_schedule.assert_called_once()
        call = mock_schedule.call_args.kwargs
        assert call["tool_name"] == "builtin_search"
        assert call["arguments"] == {"query": "hello"}
        assert call["user_id"] == "anonymous"
        assert call["result"][0].text == '{"source":"builtin"}'


# ---------------------------------------------------------------------------
# handle_tool_call — unknown tool
# ---------------------------------------------------------------------------

class TestHandleToolCallUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_raises_mcp_error(self) -> None:
        from mcp.shared.exceptions import McpError
        from mcp.types import INVALID_PARAMS

        handler, _, _ = _build_handler([_make_tool("search")])
        with pytest.raises(McpError) as exc_info:
            await handler("nonexistent_tool", {})
        assert exc_info.value.error.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_unknown_tool_error_message_contains_name(self) -> None:
        from mcp.shared.exceptions import McpError

        handler, _, _ = _build_handler([_make_tool("search")])
        with pytest.raises(McpError) as exc_info:
            await handler("missing_tool", {})
        assert "missing_tool" in exc_info.value.error.message

    @pytest.mark.asyncio
    async def test_agent_client_not_called_for_unknown_tool(self) -> None:
        from mcp.shared.exceptions import McpError

        handler, _, client = _build_handler([_make_tool("search")])
        with pytest.raises(McpError):
            await handler("ghost", {})
        client.execute.assert_not_called()


# ---------------------------------------------------------------------------
# handle_tool_call — schema validation failure
# ---------------------------------------------------------------------------

class TestHandleToolCallSchemaFailure:
    @pytest.mark.asyncio
    async def test_wrong_type_raises_mcp_error(self) -> None:
        from mcp.shared.exceptions import McpError
        from mcp.types import INVALID_PARAMS

        handler, _, _ = _build_handler([_make_tool("search")])
        with pytest.raises(McpError) as exc_info:
            # query must be a string, not an integer
            await handler("search", {"query": 123})
        assert exc_info.value.error.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_schema_error_message_is_descriptive(self) -> None:
        from mcp.shared.exceptions import McpError

        handler, _, _ = _build_handler([_make_tool("search")])
        with pytest.raises(McpError) as exc_info:
            await handler("search", {"query": 123})
        assert "Invalid arguments" in exc_info.value.error.message

    @pytest.mark.asyncio
    async def test_missing_required_argument_raises_mcp_error(self) -> None:
        from mcp.shared.exceptions import McpError
        from mcp.types import INVALID_PARAMS

        handler, _, _ = _build_handler([_make_tool("search")])
        with pytest.raises(McpError) as exc_info:
            await handler("search", {})  # 'query' is required but missing
        assert exc_info.value.error.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_extra_properties_allowed_by_default(self) -> None:
        """JSON Schema with no additionalProperties:false allows extra keys."""
        handler, _, _ = _build_handler([_make_tool("search")])
        # should NOT raise — extra keys are permitted
        result = await handler("search", {"query": "hello", "extra_key": "value"})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_agent_client_not_called_on_validation_failure(self) -> None:
        from mcp.shared.exceptions import McpError

        handler, _, client = _build_handler([_make_tool("search")])
        with pytest.raises(McpError):
            await handler("search", {})
        client.execute.assert_not_called()


# ---------------------------------------------------------------------------
# trace_id propagation
# ---------------------------------------------------------------------------

class TestTraceIdPropagation:
    @pytest.mark.asyncio
    async def test_trace_id_is_32_hex_chars(self) -> None:
        handler, _, client = _build_handler([_make_tool("search")])
        await handler("search", {"query": "test"})
        dispatch: ToolCallDispatch = client.execute.call_args[0][0]
        assert re.match(r"^[0-9a-f]{32}$", dispatch.trace_id), (
            f"trace_id not 32-char hex: {dispatch.trace_id!r}"
        )


# ---------------------------------------------------------------------------
# ToolRegistryService.get_by_name
# ---------------------------------------------------------------------------

class TestToolRegistryServiceGetByName:
    @pytest.mark.asyncio
    async def test_returns_tool_when_found(self) -> None:
        tools = [_make_tool("alpha"), _make_tool("beta")]
        registry = _make_registry(tools)
        result = await registry.get_by_name("alpha")
        assert result is not None
        assert result.name == "alpha"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        registry = _make_registry([_make_tool("alpha")])
        result = await registry.get_by_name("ghost")
        assert result is None

    @pytest.mark.asyncio
    async def test_real_service_get_by_name_miss(self) -> None:
        """Real ToolRegistryService (no repo/cache) returns None for any name."""
        service = ToolRegistryService()
        result = await service.get_by_name("anything")
        assert result is None
