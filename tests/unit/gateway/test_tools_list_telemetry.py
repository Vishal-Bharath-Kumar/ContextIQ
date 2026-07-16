"""
Unit tests for TASK-US002-05: OTel instrumentation on ``tools/list``.

Assertions:
  - handle_tools_list produces a ``mcp.tools.list`` span
  - span carries ``mcp.tools.count`` attribute matching the number of tools
  - span carries ``contextiq.cache.hit`` = True on cache hit
  - span carries ``contextiq.cache.hit`` = False on cache miss
  - Prometheus counter ``contextiq_tools_list_calls_total`` increments correctly
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.gateway.schemas.tool_types import InputSchema, ToolDefinition, ToolListResult
from src.gateway.services.tool_registry import ToolRegistryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    """Return a TracerProvider wired to an in-memory span exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _make_tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="A test tool.",
        inputSchema=InputSchema(properties={"q": {"type": "string"}}, required=["q"]),
    )


def _make_registry(tools: list[ToolDefinition], *, cache_hit: bool) -> ToolRegistryService:
    registry = MagicMock(spec=ToolRegistryService)
    registry.get_active_tools = AsyncMock(
        return_value=ToolListResult(tools=tools, cache_hit=cache_hit)
    )
    return registry


def _register_and_capture(mcp: MagicMock, registry: ToolRegistryService) -> dict:
    """Wire handler and return a dict with key ``handler`` set to the coroutine."""
    import src.gateway.handlers.tools_list as mod

    captured: dict = {}

    def _list_tools():
        def _decorator(fn: object) -> object:
            captured["handler"] = fn
            return fn
        return _decorator

    mcp.list_tools = _list_tools
    mod.register_tools_list_handler(mcp, registry=registry)
    return captured


# ---------------------------------------------------------------------------
# Span tests
# ---------------------------------------------------------------------------

class TestToolsListSpan:
    @pytest.mark.asyncio
    async def test_span_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """handle_tools_list emits a span named ``mcp.tools.list``."""
        import src.gateway.handlers.tools_list as mod

        provider, exporter = _setup_provider()
        monkeypatch.setattr(mod, "_tracer", provider.get_tracer("contextiq.gateway"))

        mcp = MagicMock()
        captured = _register_and_capture(mcp, _make_registry([_make_tool("alpha")], cache_hit=True))

        await captured["handler"]()

        spans = exporter.get_finished_spans()
        assert any(s.name == "mcp.tools.list" for s in spans)

    @pytest.mark.asyncio
    async def test_span_tools_count_attribute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``mcp.tools.count`` equals the number of tools returned."""
        import src.gateway.handlers.tools_list as mod

        provider, exporter = _setup_provider()
        monkeypatch.setattr(mod, "_tracer", provider.get_tracer("contextiq.gateway"))

        mcp = MagicMock()
        tools = [_make_tool(f"t{i}") for i in range(5)]
        captured = _register_and_capture(mcp, _make_registry(tools, cache_hit=False))

        await captured["handler"]()

        spans = exporter.get_finished_spans()
        target = next(s for s in spans if s.name == "mcp.tools.list")
        assert target.attributes["mcp.tools.count"] == 5

    @pytest.mark.asyncio
    async def test_span_cache_hit_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``contextiq.cache.hit`` is ``True`` when the result comes from cache."""
        import src.gateway.handlers.tools_list as mod

        provider, exporter = _setup_provider()
        monkeypatch.setattr(mod, "_tracer", provider.get_tracer("contextiq.gateway"))

        mcp = MagicMock()
        captured = _register_and_capture(
            mcp, _make_registry([_make_tool("cached_tool")], cache_hit=True)
        )

        await captured["handler"]()

        spans = exporter.get_finished_spans()
        target = next(s for s in spans if s.name == "mcp.tools.list")
        assert target.attributes["contextiq.cache.hit"] is True

    @pytest.mark.asyncio
    async def test_span_cache_hit_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``contextiq.cache.hit`` is ``False`` on a cache miss (DB path)."""
        import src.gateway.handlers.tools_list as mod

        provider, exporter = _setup_provider()
        monkeypatch.setattr(mod, "_tracer", provider.get_tracer("contextiq.gateway"))

        mcp = MagicMock()
        captured = _register_and_capture(
            mcp, _make_registry([_make_tool("db_tool")], cache_hit=False)
        )

        await captured["handler"]()

        spans = exporter.get_finished_spans()
        target = next(s for s in spans if s.name == "mcp.tools.list")
        assert target.attributes["contextiq.cache.hit"] is False

    @pytest.mark.asyncio
    async def test_returns_tool_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """handler returns the tool list from the registry unchanged."""
        import src.gateway.handlers.tools_list as mod

        provider, _ = _setup_provider()
        monkeypatch.setattr(mod, "_tracer", provider.get_tracer("contextiq.gateway"))

        mcp = MagicMock()
        tools = [_make_tool("alpha"), _make_tool("beta")]
        captured = _register_and_capture(mcp, _make_registry(tools, cache_hit=True))

        result = await captured["handler"]()
        assert result == tools


# ---------------------------------------------------------------------------
# Prometheus counter tests
# ---------------------------------------------------------------------------

class TestToolsListPrometheusCounter:
    @pytest.mark.asyncio
    async def test_counter_increments_on_cache_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``contextiq_tools_list_calls_total{cache_hit="true"}`` increments."""
        import src.gateway.handlers.tools_list as mod

        provider, _ = _setup_provider()
        monkeypatch.setattr(mod, "_tracer", provider.get_tracer("contextiq.gateway"))

        mcp = MagicMock()
        captured = _register_and_capture(
            mcp, _make_registry([_make_tool("hit_tool")], cache_hit=True)
        )

        before = mod.tools_list_calls_total.labels(cache_hit="true")._value.get()
        await captured["handler"]()
        after = mod.tools_list_calls_total.labels(cache_hit="true")._value.get()

        assert after == before + 1.0

    @pytest.mark.asyncio
    async def test_counter_increments_on_cache_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``contextiq_tools_list_calls_total{cache_hit="false"}`` increments."""
        import src.gateway.handlers.tools_list as mod

        provider, _ = _setup_provider()
        monkeypatch.setattr(mod, "_tracer", provider.get_tracer("contextiq.gateway"))

        mcp = MagicMock()
        captured = _register_and_capture(mcp, _make_registry([], cache_hit=False))

        before = mod.tools_list_calls_total.labels(cache_hit="false")._value.get()
        await captured["handler"]()
        after = mod.tools_list_calls_total.labels(cache_hit="false")._value.get()

        assert after == before + 1.0

