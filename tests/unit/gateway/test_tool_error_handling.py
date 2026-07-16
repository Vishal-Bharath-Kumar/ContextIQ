"""
Unit tests for TASK-US003-03: Structured Error Handling for Tool Call Failures.

Covers all 7 failure modes in the error taxonomy:
  1. Tool not found             → isError payload, code -32602
  2. Input schema violation     → isError payload, code -32602
  3. Agent Worker timeout       → isError payload, code -32603, timeout_ms detail
  4. Agent Worker 5xx           → isError payload, code -32603
  5. Circuit breaker open       → isError payload, code -32001, retry_after_seconds
  6. Agent pipeline logic error → isError payload, code -32603
  7. Unexpected exception       → isError payload, code -32603

Also tests:
  - Session persistence: error followed by success in same handler instance
  - ``tool_call_errors_total`` counter increments per error_type label
  - ASGI ErrorHandlerMiddleware returns 500 JSON on unhandled exceptions
  - ``build_tool_error`` helper encodes payload correctly
"""
from __future__ import annotations

import json
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import httpx
import pybreaker
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import TextContent

from src.gateway.errors.tool_errors import (
    CIRCUIT_BREAKER_OPEN,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    build_tool_error,
)
from src.gateway.handlers.tools_call import (
    register_tools_call_handler,
    set_user_id_context,
    tool_call_errors_total,
)
from src.gateway.middleware.error_handler import ErrorHandlerMiddleware
from src.gateway.schemas.call_types import ToolCallDispatch, ToolCallOutput
from src.gateway.schemas.tool_types import InputSchema, ToolDefinition
from src.gateway.services.tool_registry import ToolRegistryService

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str = "search") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Description of {name}.",
        inputSchema=InputSchema(
            properties={"query": {"type": "string"}},
            required=["query"],
        ),
    )


def _make_registry(tools: list[ToolDefinition]) -> ToolRegistryService:
    registry = MagicMock(spec=ToolRegistryService)

    async def _get_by_name(name: str) -> ToolDefinition | None:
        return next((t for t in tools if t.name == name), None)

    registry.get_by_name = AsyncMock(side_effect=_get_by_name)
    return registry


def _make_agent_client(side_effect: object = None, output: object = "ok") -> object:
    client = MagicMock()
    if side_effect is not None:
        client.execute = AsyncMock(side_effect=side_effect)
    else:
        async def _execute(dispatch: ToolCallDispatch) -> ToolCallOutput:
            return ToolCallOutput(data=output)
        client.execute = AsyncMock(side_effect=_execute)
    return client


def _build_handler(
    tools: list[ToolDefinition],
    agent_side_effect: object = None,
    agent_output: object = "ok",
) -> tuple[object, object]:
    """Return (handler_coroutine, agent_client_mock)."""
    registry = _make_registry(tools)
    agent_client = _make_agent_client(side_effect=agent_side_effect, output=agent_output)

    captured: list[object] = []

    def _call_tool_decorator() -> Callable[[object], object]:
        def _inner(fn: object) -> object:
            captured.append(fn)
            return fn
        return _inner

    mock_mcp = MagicMock()
    mock_mcp.call_tool = _call_tool_decorator

    register_tools_call_handler(mock_mcp, registry=registry, agent_client=agent_client)
    assert captured, "No handler registered via @mcp.call_tool()"
    return captured[0], agent_client


def _parse_error(result: list[TextContent]) -> dict:
    """Parse the error dict from a build_tool_error TextContent result."""
    assert len(result) == 1
    return json.loads(result[0].text)["error"]


# ---------------------------------------------------------------------------
# build_tool_error unit tests
# ---------------------------------------------------------------------------


class TestBuildToolError:
    def test_returns_text_content_list(self) -> None:
        result = build_tool_error(INTERNAL_ERROR, "oops")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"

    def test_payload_contains_code_and_message(self) -> None:
        err = _parse_error(build_tool_error(INTERNAL_ERROR, "boom"))
        assert err["code"] == INTERNAL_ERROR
        assert err["message"] == "boom"

    def test_payload_without_detail_has_no_data_key(self) -> None:
        err = _parse_error(build_tool_error(INVALID_PARAMS, "bad"))
        assert "data" not in err

    def test_payload_with_detail_includes_data(self) -> None:
        err = _parse_error(build_tool_error(INTERNAL_ERROR, "t/o", {"timeout_ms": 5000}))
        assert err["data"] == {"timeout_ms": 5000}

    def test_circuit_breaker_code(self) -> None:
        err = _parse_error(build_tool_error(CIRCUIT_BREAKER_OPEN, "unavailable", {"retry_after_seconds": 60}))
        assert err["code"] == CIRCUIT_BREAKER_OPEN
        assert err["data"]["retry_after_seconds"] == 60


# ---------------------------------------------------------------------------
# Failure mode 1: Tool not found
# ---------------------------------------------------------------------------


class TestToolNotFound:
    @pytest.mark.asyncio
    async def test_tool_not_found_raises_mcp_error(self) -> None:
        handler, _ = _build_handler([_make_tool("known")])
        with pytest.raises(McpError) as exc_info:
            await handler("unknown_tool", {"query": "x"})
        assert exc_info.value.error.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_tool_not_found_message_contains_name(self) -> None:
        handler, _ = _build_handler([])
        with pytest.raises(McpError) as exc_info:
            await handler("missing", {"query": "x"})
        assert "missing" in exc_info.value.error.message


# ---------------------------------------------------------------------------
# Failure mode 2: Input schema violation
# ---------------------------------------------------------------------------


class TestInputSchemaViolation:
    @pytest.mark.asyncio
    async def test_wrong_type_raises_mcp_error(self) -> None:
        handler, _ = _build_handler([_make_tool("search")])
        with pytest.raises(McpError) as exc_info:
            await handler("search", {"query": 123})  # integer instead of string
        assert exc_info.value.error.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_missing_required_arg_raises_mcp_error(self) -> None:
        handler, _ = _build_handler([_make_tool("search")])
        with pytest.raises(McpError) as exc_info:
            await handler("search", {})  # missing required "query"
        assert exc_info.value.error.code == INVALID_PARAMS


# ---------------------------------------------------------------------------
# Failure mode 3: Agent Worker timeout
# ---------------------------------------------------------------------------


class TestAgentWorkerTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_is_error_content(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=httpx.ReadTimeout("timed out"),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["code"] == INTERNAL_ERROR
        assert "timed out" in err["message"].lower()

    @pytest.mark.asyncio
    async def test_timeout_detail_contains_timeout_ms(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=httpx.ConnectTimeout("timeout"),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert "timeout_ms" in err["data"]

    @pytest.mark.asyncio
    async def test_timeout_increments_error_counter(self) -> None:
        before = _counter_value("search", "timeout")
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=httpx.ReadTimeout("t/o"),
        )
        await handler("search", {"query": "q"})
        assert _counter_value("search", "timeout") == before + 1

    @pytest.mark.asyncio
    async def test_write_timeout_also_caught(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=httpx.WriteTimeout("write t/o"),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["code"] == INTERNAL_ERROR


# ---------------------------------------------------------------------------
# Failure mode 4: Agent Worker 5xx (HTTPStatusError)
# ---------------------------------------------------------------------------


class TestAgentWorker5xx:
    @pytest.mark.asyncio
    async def test_http_status_error_returns_internal_error(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 503
        exc = httpx.HTTPStatusError("503", request=MagicMock(), response=response)
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=exc,
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["code"] == INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_http_status_error_increments_unknown_counter(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 500
        exc = httpx.HTTPStatusError("500", request=MagicMock(), response=response)
        before = _counter_value("search", "unknown")
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=exc,
        )
        await handler("search", {"query": "q"})
        assert _counter_value("search", "unknown") == before + 1


# ---------------------------------------------------------------------------
# Failure mode 5: Circuit breaker open
# ---------------------------------------------------------------------------


class TestCircuitBreakerOpen:
    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_custom_code(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=pybreaker.CircuitBreakerError(),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["code"] == CIRCUIT_BREAKER_OPEN

    @pytest.mark.asyncio
    async def test_circuit_breaker_detail_has_retry_after(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=pybreaker.CircuitBreakerError(),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["data"]["retry_after_seconds"] == 60

    @pytest.mark.asyncio
    async def test_circuit_breaker_message(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=pybreaker.CircuitBreakerError(),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert "unavailable" in err["message"].lower()


# ---------------------------------------------------------------------------
# Failure mode 6: Agent pipeline logic error (generic RuntimeError)
# ---------------------------------------------------------------------------


class TestAgentPipelineError:
    @pytest.mark.asyncio
    async def test_pipeline_error_returns_internal_error(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=RuntimeError("pipeline exploded"),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["code"] == INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_pipeline_error_increments_unknown_counter(self) -> None:
        before = _counter_value("search", "unknown")
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=RuntimeError("boom"),
        )
        await handler("search", {"query": "q"})
        assert _counter_value("search", "unknown") == before + 1


# ---------------------------------------------------------------------------
# Failure mode 7: Unexpected exception (e.g. KeyError)
# ---------------------------------------------------------------------------


class TestUnexpectedException:
    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_internal_error(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=KeyError("unexpected"),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["code"] == INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_unexpected_exception_detail_has_tool_name(self) -> None:
        handler, _ = _build_handler(
            [_make_tool("search")],
            agent_side_effect=ValueError("oops"),
        )
        result = await handler("search", {"query": "q"})
        err = _parse_error(result)
        assert err["data"]["tool"] == "search"


# ---------------------------------------------------------------------------
# Session persistence: error followed by successful call
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    @pytest.mark.asyncio
    async def test_error_then_success_same_handler(self) -> None:
        """The handler must remain usable after returning an error payload."""
        registry = _make_registry([_make_tool("search")])

        call_count = {"n": 0}

        async def _flaky_execute(dispatch: ToolCallDispatch) -> ToolCallOutput:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.ReadTimeout("first call times out")
            return ToolCallOutput(data={"answer": "ok"})

        client = MagicMock()
        client.execute = AsyncMock(side_effect=_flaky_execute)

        captured: list[object] = []

        def _decorator() -> Callable[[object], object]:
            def _inner(fn: object) -> object:
                captured.append(fn)
                return fn
            return _inner

        mock_mcp = MagicMock()
        mock_mcp.call_tool = _decorator
        register_tools_call_handler(mock_mcp, registry=registry, agent_client=client)
        handler = captured[0]

        # First call — timeout → error payload (not an exception)
        error_result = await handler("search", {"query": "first"})
        err = _parse_error(error_result)
        assert err["code"] == INTERNAL_ERROR

        # Second call — success
        success_result = await handler("search", {"query": "second"})
        parsed = json.loads(success_result[0].text)
        assert parsed == {"answer": "ok"}


# ---------------------------------------------------------------------------
# ASGI ErrorHandlerMiddleware
# ---------------------------------------------------------------------------


class TestErrorHandlerMiddleware:
    @pytest.mark.asyncio
    async def test_passes_through_normal_response(self) -> None:
        async def _ok_app(scope, receive, send) -> None:  # noqa: ANN001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok", "more_body": False})

        responses: list[dict] = []

        async def _send(event: dict) -> None:
            responses.append(event)

        middleware = ErrorHandlerMiddleware(_ok_app)
        await middleware({"type": "http"}, None, _send)
        assert responses[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_converts_unhandled_exception_to_500(self) -> None:
        async def _boom_app(scope, receive, send) -> None:  # noqa: ANN001
            raise RuntimeError("something broke")

        responses: list[dict] = []

        async def _send(event: dict) -> None:
            responses.append(event)

        middleware = ErrorHandlerMiddleware(_boom_app)
        await middleware({"type": "http"}, None, _send)
        assert responses[0]["status"] == 500

    @pytest.mark.asyncio
    async def test_500_body_is_valid_json_rpc_error(self) -> None:
        async def _boom_app(scope, receive, send) -> None:  # noqa: ANN001
            raise ValueError("oops")

        body_chunks: list[bytes] = []

        async def _send(event: dict) -> None:
            if event["type"] == "http.response.body":
                body_chunks.append(event["body"])

        middleware = ErrorHandlerMiddleware(_boom_app)
        await middleware({"type": "http"}, None, _send)
        body = json.loads(b"".join(body_chunks))
        assert body["error"]["code"] == INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_non_http_scope_forwarded_unchanged(self) -> None:
        called: list[bool] = []

        async def _inner_app(scope, receive, send) -> None:  # noqa: ANN001
            called.append(True)

        middleware = ErrorHandlerMiddleware(_inner_app)
        await middleware({"type": "websocket"}, None, None)
        assert called == [True]


# ---------------------------------------------------------------------------
# Counter helper
# ---------------------------------------------------------------------------


def _counter_value(tool_name: str, error_type: str) -> float:
    """Read the current value of the tool_call_errors_total counter."""
    try:
        return tool_call_errors_total.labels(
            tool_name=tool_name, error_type=error_type
        )._value.get()
    except Exception:  # noqa: BLE001
        return 0.0
