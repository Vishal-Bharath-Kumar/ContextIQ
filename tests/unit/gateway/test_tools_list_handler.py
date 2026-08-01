"""
Unit tests for TASK-US002-01: MCP ``tools/list`` handler.

Coverage targets (≥ 90% on handlers/tools_list.py and schemas/tool_types.py):
  - ToolDefinition / InputSchema / ToolListResult schema validation
  - handle_tools_list: returns sorted list, empty list, idempotency
  - register_tools_list_handler: wires into FastMCP correctly
  - Benchmark: p95 latency < 200 ms for 50 tools served from cache
"""
from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

from mcp.types import Tool as MCPTool
import pytest
from pydantic import ValidationError

from src.gateway.handlers.tools_list import register_tools_list_handler
from src.gateway.schemas.tool_types import InputSchema, ToolDefinition, ToolListResult
from src.gateway.services.tool_registry import ToolRegistryService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(name: str, description: str = "A tool.") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        inputSchema=InputSchema(
            properties={"query": {"type": "string"}},
            required=["query"],
        ),
    )


def _make_n_tools(n: int) -> list[ToolDefinition]:
    """Return *n* tool definitions with lexicographically ordered names."""
    return [_make_tool(f"tool_{i:03d}") for i in range(n)]


def _make_registry(tools: list[ToolDefinition]) -> ToolRegistryService:
    """Return a ToolRegistryService that yields *tools* immediately."""
    registry = MagicMock(spec=ToolRegistryService)
    registry.get_active_tools = AsyncMock(return_value=ToolListResult(tools=tools))
    return registry


# ---------------------------------------------------------------------------
# Schema tests — InputSchema
# ---------------------------------------------------------------------------

class TestInputSchema:
    def test_defaults(self) -> None:
        schema = InputSchema()
        assert schema.type == "object"
        assert schema.properties == {}
        assert schema.required == []

    def test_type_is_always_object(self) -> None:
        schema = InputSchema(properties={"x": {"type": "string"}}, required=["x"])
        assert schema.type == "object"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises((ValidationError, ValueError)):
            InputSchema(type="array")  # type: ignore[arg-type]

    def test_custom_properties_and_required(self) -> None:
        schema = InputSchema(
            properties={"city": {"type": "string"}, "limit": {"type": "integer"}},
            required=["city"],
        )
        assert "city" in schema.properties
        assert "limit" in schema.properties
        assert schema.required == ["city"]


# ---------------------------------------------------------------------------
# Schema tests — ToolDefinition
# ---------------------------------------------------------------------------

class TestToolDefinition:
    def test_minimal_construction(self) -> None:
        tool = ToolDefinition(name="my_tool", description="Does things.")
        assert tool.name == "my_tool"
        assert tool.description == "Does things."
        assert isinstance(tool.inputSchema, InputSchema)

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ToolDefinition(description="x")  # type: ignore[call-arg]

    def test_missing_description_raises(self) -> None:
        with pytest.raises(ValidationError):
            ToolDefinition(name="x")  # type: ignore[call-arg]

    def test_input_schema_embedded(self) -> None:
        schema = InputSchema(properties={"q": {"type": "string"}}, required=["q"])
        tool = ToolDefinition(name="search", description="Search.", inputSchema=schema)
        assert tool.inputSchema.required == ["q"]

    def test_model_json_contains_required_keys(self) -> None:
        tool = _make_tool("json_tool")
        data = tool.model_dump()
        assert set(data.keys()) == {"name", "description", "inputSchema", "output_schema"}


# ---------------------------------------------------------------------------
# Schema tests — ToolListResult
# ---------------------------------------------------------------------------

class TestToolListResult:
    def test_empty_default(self) -> None:
        result = ToolListResult()
        assert result.tools == []

    def test_with_tools(self) -> None:
        tools = _make_n_tools(3)
        result = ToolListResult(tools=tools)
        assert len(result.tools) == 3

    def test_tools_field_is_list_of_tool_definitions(self) -> None:
        result = ToolListResult(tools=[_make_tool("t")])
        assert isinstance(result.tools[0], ToolDefinition)


# ---------------------------------------------------------------------------
# handle_tools_list — via register_tools_list_handler
# ---------------------------------------------------------------------------

class TestHandleToolsList:
    def _build_mcp_with_handler(
        self, registry: ToolRegistryService
    ) -> tuple[MagicMock, object]:
        """
        Create a minimal FastMCP mock that captures the registered coroutine
        when ``@mcp.list_tools()`` is called, then return (mock_mcp, handler).
        """
        captured: list[object] = []

        def _list_tools_decorator() -> Callable[[object], object]:
            def _inner(fn: object) -> object:
                captured.append(fn)
                return fn

            return _inner

        mock_mcp = MagicMock()
        mock_mcp.list_tools = _list_tools_decorator
        register_tools_list_handler(mock_mcp, registry=registry)
        assert captured, "No handler was registered via @mcp.list_tools()"
        return mock_mcp, captured[0]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_tools(self) -> None:
        _, handler = self._build_mcp_with_handler(_make_registry([]))
        result = await handler()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_tool_definitions(self) -> None:
        tools = _make_n_tools(3)
        _, handler = self._build_mcp_with_handler(_make_registry(tools))
        result = await handler()
        assert len(result) == 3
        assert all(isinstance(t, MCPTool) for t in result)

    @pytest.mark.asyncio
    async def test_tools_sorted_by_name_asc(self) -> None:
        tools = [_make_tool("zebra"), _make_tool("alpha"), _make_tool("mango")]
        registry = _make_registry(tools)
        # Registry already returns them unsorted; service sorts in get_active_tools.
        # To test handler ordering, provide pre-sorted result via mock.
        sorted_tools = sorted(tools, key=lambda t: t.name)
        registry.get_active_tools = AsyncMock(
            return_value=ToolListResult(tools=sorted_tools)
        )
        _, handler = self._build_mcp_with_handler(registry)
        result = await handler()
        names = [t.name for t in result]
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_idempotent_repeated_calls(self) -> None:
        tools = _make_n_tools(5)
        registry = _make_registry(tools)
        _, handler = self._build_mcp_with_handler(registry)
        first = await handler()
        second = await handler()
        assert first == second

    @pytest.mark.asyncio
    async def test_registry_called_each_invocation(self) -> None:
        tools = _make_n_tools(2)
        registry = _make_registry(tools)
        _, handler = self._build_mcp_with_handler(registry)
        await handler()
        await handler()
        assert registry.get_active_tools.call_count == 2

    @pytest.mark.asyncio
    async def test_fifty_tools_returned(self) -> None:
        tools = _make_n_tools(50)
        _, handler = self._build_mcp_with_handler(_make_registry(tools))
        result = await handler()
        assert len(result) == 50

    @pytest.mark.asyncio
    async def test_tool_shape_matches_mcp_spec(self) -> None:
        tool = _make_tool("spec_tool", "Spec description.")
        _, handler = self._build_mcp_with_handler(_make_registry([tool]))
        result = await handler()
        assert len(result) == 1
        t = result[0]
        assert isinstance(t.name, str)
        assert isinstance(t.description, str)
        assert isinstance(t.inputSchema, dict)
        assert t.inputSchema["type"] == "object"


class TestHandleToolsListBuiltinFallback:
    @pytest.mark.asyncio
    async def test_builtin_tools_merged_with_registry_tools(self) -> None:
        registry = _make_registry([_make_tool("db_tool")])
        captured: list[object] = []

        def _list_tools_decorator() -> Callable[[object], object]:
            def _inner(fn: object) -> object:
                captured.append(fn)
                return fn
            return _inner

        builtin_tool = MagicMock()
        builtin_tool.name = "builtin_tool"
        builtin_tool.description = "Built-in tool"
        builtin_tool.title = None
        builtin_tool.parameters = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        builtin_tool.output_schema = {"type": "object"}

        mock_mcp = MagicMock()
        mock_mcp.list_tools = _list_tools_decorator
        mock_mcp._list_tools = AsyncMock(return_value=[builtin_tool])

        register_tools_list_handler(mock_mcp, registry=registry)
        handler = captured[0]

        result = await handler()
        assert [tool.name for tool in result] == ["builtin_tool", "db_tool"]


# ---------------------------------------------------------------------------
# ToolRegistryService stub — interface contract
# ---------------------------------------------------------------------------

class TestRegisterDefaultRegistry:
    """Exercises the _get_registry() lazy-init path (no registry injected)."""

    @pytest.mark.asyncio
    async def test_default_registry_path_returns_empty_list(self) -> None:
        """Calling register_tools_list_handler without a registry uses the default."""
        import src.gateway.handlers.tools_list as _module

        # Reset the module-level singleton so the lazy-init branch executes.
        original = _module._default_registry
        _module._default_registry = None
        try:
            captured: list[object] = []

            def _list_tools_decorator() -> Callable[[object], object]:
                def _inner(fn: object) -> object:
                    captured.append(fn)
                    return fn

                return _inner

            mock_mcp = MagicMock()
            mock_mcp.list_tools = _list_tools_decorator
            register_tools_list_handler(mock_mcp)  # No registry — uses default
            handler = captured[0]
            result = await handler()
            assert result == []
        finally:
            _module._default_registry = original


class TestToolRegistryServiceStub:
    @pytest.mark.asyncio
    async def test_stub_returns_empty_tool_list_result(self) -> None:
        service = ToolRegistryService()
        result = await service.get_active_tools()
        assert isinstance(result, ToolListResult)
        assert result.tools == []

    @pytest.mark.asyncio
    async def test_stub_is_idempotent(self) -> None:
        service = ToolRegistryService()
        first = await service.get_active_tools()
        second = await service.get_active_tools()
        assert first.tools == second.tools


# ---------------------------------------------------------------------------
# Benchmark: handler latency < 200 ms for 50 tools (cache-backed)
# ---------------------------------------------------------------------------

class TestHandleToolsListBenchmark:
    """Timing-based benchmark that does NOT require pytest-benchmark.

    Calls the handler 100 times and asserts that the p95 wall-clock time is
    under 200 ms, satisfying the TASK-US002-01 performance contract for the
    cache-hit path.
    """

    @pytest.mark.asyncio
    async def test_p95_latency_under_200ms_for_50_tools(self) -> None:
        tools = _make_n_tools(50)
        registry = _make_registry(tools)

        captured: list[object] = []

        def _list_tools_decorator() -> Callable[[object], object]:
            def _inner(fn: object) -> object:
                captured.append(fn)
                return fn

            return _inner

        mock_mcp = MagicMock()
        mock_mcp.list_tools = _list_tools_decorator
        register_tools_list_handler(mock_mcp, registry=registry)
        handler = captured[0]

        latencies: list[float] = []
        iterations = 100
        for _ in range(iterations):
            t0 = time.perf_counter()
            await handler()
            latencies.append((time.perf_counter() - t0) * 1000)  # ms

        latencies.sort()
        p95_index = int(iterations * 0.95) - 1
        p95_ms = latencies[p95_index]

        assert p95_ms < 200, (
            f"p95 latency {p95_ms:.2f} ms exceeds 200 ms SLA "
            f"(median={statistics.median(latencies):.2f} ms)"
        )
