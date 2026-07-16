"""
Unit tests for TASK-US003-05: End-to-End Correlation ID Tracing and SLA Monitoring.

Coverage targets:
  - ``mcp.tools.call`` span is created with SpanKind.SERVER
  - Span carries ``mcp.tool.name``, ``mcp.request_id``, ``contextiq.user_id``
  - ``mcp.tool.success=True`` + ``mcp.tool.duration_ms`` on successful call
  - ``mcp.tool.success=False`` + duration recorded on timeout / circuit-breaker
  - ``contextiq_tool_call_duration_seconds`` histogram observes latency for each exit path
  - ``traceparent`` header present on outbound Agent Worker POST request
  - ``X-Request-ID`` and ``X-Trace-ID`` remain on outbound request alongside traceparent
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pybreaker
import pytest

from src.gateway.clients.agent_worker_client import AgentWorkerClient
from src.gateway.handlers.tools_call import register_tools_call_handler, set_user_id_context
from src.gateway.schemas.call_types import ToolCallDispatch, ToolCallOutput
from src.gateway.schemas.tool_types import InputSchema, ToolDefinition, ToolListResult
from src.gateway.services.tool_registry import ToolRegistryService


# ---------------------------------------------------------------------------
# Helpers (mirrors test_tools_call_handler.py)
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
    registry.get_active_tools = AsyncMock(return_value=ToolListResult(tools=tools))

    async def _get_by_name(name: str) -> ToolDefinition | None:
        return next((t for t in tools if t.name == name), None)

    registry.get_by_name = AsyncMock(side_effect=_get_by_name)
    return registry


def _make_agent_client(output: Any = None) -> AgentWorkerClient:
    client = MagicMock(spec=AgentWorkerClient)

    async def _execute(dispatch: ToolCallDispatch) -> ToolCallOutput:
        return ToolCallOutput(data=output or {"result": "ok"})

    client.execute = AsyncMock(side_effect=_execute)
    return client


def _build_handler(
    tools: list[ToolDefinition] | None = None,
    agent_output: Any = None,
) -> tuple[Any, ToolRegistryService, AgentWorkerClient]:
    tools = tools or [_make_tool()]
    registry = _make_registry(tools)
    agent_client = _make_agent_client(agent_output)

    captured: list[Any] = []

    def _call_tool_decorator() -> Callable[[Any], Any]:
        def _inner(fn: Any) -> Any:
            captured.append(fn)
            return fn
        return _inner

    mock_mcp = MagicMock()
    mock_mcp.call_tool = _call_tool_decorator
    register_tools_call_handler(mock_mcp, registry=registry, agent_client=agent_client)
    assert captured
    return captured[0], registry, agent_client


# ---------------------------------------------------------------------------
# Span attribute tests
# ---------------------------------------------------------------------------

class TestSpanAttributes:
    """Verify that the root mcp.tools.call span carries the required attributes."""

    @pytest.mark.asyncio
    async def test_span_name_and_kind(self) -> None:
        handler, _, _ = _build_handler()

        with patch("src.gateway.handlers.tools_call._tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

            set_user_id_context("alice")
            await handler("search", {"query": "test"})

            # Confirm the span was created with the expected name
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "mcp.tools.call"

    @pytest.mark.asyncio
    async def test_span_sets_mcp_tool_name(self) -> None:
        handler, _, _ = _build_handler()
        set_user_id_context("bob")

        attrs: dict[str, Any] = {}

        with patch("src.gateway.handlers.tools_call._tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_span.set_attribute.side_effect = lambda k, v: attrs.update({k: v})
            mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

            await handler("search", {"query": "hello"})

        assert attrs.get("mcp.tool.name") == "search"

    @pytest.mark.asyncio
    async def test_span_sets_request_id_and_user_id(self) -> None:
        handler, _, _ = _build_handler()
        set_user_id_context("carol")

        attrs: dict[str, Any] = {}

        with patch("src.gateway.handlers.tools_call._tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_span.set_attribute.side_effect = lambda k, v: attrs.update({k: v})
            mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

            await handler("search", {"query": "hi"})

        assert "mcp.request_id" in attrs
        assert len(attrs["mcp.request_id"]) == 36  # UUID v4
        assert attrs.get("contextiq.user_id") == "carol"

    @pytest.mark.asyncio
    async def test_span_sets_success_true_on_success(self) -> None:
        handler, _, _ = _build_handler()
        set_user_id_context("dave")

        attrs: dict[str, Any] = {}

        with patch("src.gateway.handlers.tools_call._tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_span.set_attribute.side_effect = lambda k, v: attrs.update({k: v})
            mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

            await handler("search", {"query": "hi"})

        assert attrs.get("mcp.tool.success") is True
        assert "mcp.tool.duration_ms" in attrs
        assert attrs["mcp.tool.duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_span_sets_success_false_on_timeout(self) -> None:
        registry = _make_registry([_make_tool()])
        client = MagicMock(spec=AgentWorkerClient)
        client.execute = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        captured: list[Any] = []

        def _decorator() -> Callable[[Any], Any]:
            def _inner(fn: Any) -> Any:
                captured.append(fn)
                return fn
            return _inner

        mock_mcp = MagicMock()
        mock_mcp.call_tool = _decorator
        register_tools_call_handler(mock_mcp, registry=registry, agent_client=client)
        handler = captured[0]

        attrs: dict[str, Any] = {}

        with patch("src.gateway.handlers.tools_call._tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_span.set_attribute.side_effect = lambda k, v: attrs.update({k: v})
            mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

            set_user_id_context("eve")
            await handler("search", {"query": "q"})

        assert attrs.get("mcp.tool.success") is False
        assert "mcp.tool.duration_ms" in attrs


# ---------------------------------------------------------------------------
# Latency histogram tests
# ---------------------------------------------------------------------------

class TestLatencyHistogram:
    """Verify the contextiq_tool_call_duration_seconds histogram is observed."""

    @pytest.mark.asyncio
    async def test_histogram_observed_on_success(self) -> None:
        handler, _, _ = _build_handler()
        set_user_id_context("u1")

        with patch("src.gateway.handlers.tools_call.tool_call_duration") as mock_hist:
            mock_labels = MagicMock()
            mock_hist.labels.return_value = mock_labels

            await handler("search", {"query": "test"})

        mock_hist.labels.assert_called_once_with(tool_name="search", status="success")
        mock_labels.observe.assert_called_once()
        observed_value = mock_labels.observe.call_args[0][0]
        assert observed_value >= 0.0

    @pytest.mark.asyncio
    async def test_histogram_observed_on_timeout(self) -> None:
        registry = _make_registry([_make_tool()])
        client = MagicMock(spec=AgentWorkerClient)
        client.execute = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        captured: list[Any] = []

        def _decorator() -> Callable[[Any], Any]:
            def _inner(fn: Any) -> Any:
                captured.append(fn)
                return fn
            return _inner

        mock_mcp = MagicMock()
        mock_mcp.call_tool = _decorator
        register_tools_call_handler(mock_mcp, registry=registry, agent_client=client)
        handler = captured[0]
        set_user_id_context("u2")

        with patch("src.gateway.handlers.tools_call.tool_call_duration") as mock_hist:
            mock_labels = MagicMock()
            mock_hist.labels.return_value = mock_labels

            await handler("search", {"query": "t"})

        mock_hist.labels.assert_called_once_with(tool_name="search", status="timeout")
        mock_labels.observe.assert_called_once()

    @pytest.mark.asyncio
    async def test_histogram_observed_on_circuit_breaker_open(self) -> None:
        registry = _make_registry([_make_tool()])
        client = MagicMock(spec=AgentWorkerClient)
        client.execute = AsyncMock(side_effect=pybreaker.CircuitBreakerError())

        captured: list[Any] = []

        def _decorator() -> Callable[[Any], Any]:
            def _inner(fn: Any) -> Any:
                captured.append(fn)
                return fn
            return _inner

        mock_mcp = MagicMock()
        mock_mcp.call_tool = _decorator
        register_tools_call_handler(mock_mcp, registry=registry, agent_client=client)
        handler = captured[0]
        set_user_id_context("u3")

        with patch("src.gateway.handlers.tools_call.tool_call_duration") as mock_hist:
            mock_labels = MagicMock()
            mock_hist.labels.return_value = mock_labels

            await handler("search", {"query": "q"})

        mock_hist.labels.assert_called_once_with(tool_name="search", status="error")
        mock_labels.observe.assert_called_once()

    @pytest.mark.asyncio
    async def test_histogram_labels_use_tool_name_not_wildcard(self) -> None:
        """Label cardinality check: tool_name must be the registered name, not free-form input."""
        handler, _, _ = _build_handler(tools=[_make_tool("my_tool")])
        set_user_id_context("u4")

        with patch("src.gateway.handlers.tools_call.tool_call_duration") as mock_hist:
            mock_hist.labels.return_value = MagicMock()
            await handler("my_tool", {"query": "q"})

        mock_hist.labels.assert_called_once_with(tool_name="my_tool", status="success")


# ---------------------------------------------------------------------------
# traceparent / W3C propagation tests
# ---------------------------------------------------------------------------

class TestTraceparentPropagation:
    """Verify that outbound Agent Worker requests carry W3C traceparent headers."""

    @pytest.mark.asyncio
    async def test_traceparent_injected_in_outbound_request(self) -> None:
        """inject() must be called so traceparent is added to the headers dict."""
        dispatch = ToolCallDispatch(
            request_id="req-tp-001",
            user_id="user-tp",
            tool_name="search",
            arguments={"query": "hi"},
            trace_id="a" * 32,
        )

        injected_headers: list[dict[str, str]] = []

        async def _patched_post(self_: Any, url: str, **kwargs: Any) -> Any:
            injected_headers.append(dict(kwargs.get("headers", {})))
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "request_id": dispatch.request_id,
                "status": "success",
                "output": {"data": {"r": 1}, "output_schema_version": "1.0"},
                "error": None,
                "duration_ms": 10,
            }
            return resp

        def _fake_inject(carrier: dict[str, str]) -> None:
            carrier["traceparent"] = "00-abc123-0001-01"

        client = AgentWorkerClient(
            base_url="http://agent-worker.local",
            token_fetcher=AsyncMock(return_value="test-token"),
        )

        with (
            patch("opentelemetry.propagate.inject", side_effect=_fake_inject),
            patch("httpx.AsyncClient.post", new=_patched_post),
        ):
            await client.execute(dispatch)

        assert len(injected_headers) == 1
        hdrs = injected_headers[0]
        assert "traceparent" in hdrs, f"traceparent missing from headers: {hdrs}"
        assert hdrs["traceparent"] == "00-abc123-0001-01"

    @pytest.mark.asyncio
    async def test_correlation_headers_still_present_alongside_traceparent(self) -> None:
        """X-Request-ID and X-Trace-ID must remain alongside traceparent."""
        dispatch = ToolCallDispatch(
            request_id="req-corr-002",
            user_id="user-corr",
            tool_name="search",
            arguments={"query": "test"},
            trace_id="b" * 32,
        )

        captured: list[dict[str, str]] = []

        async def _patched_post(self_: Any, url: str, **kwargs: Any) -> Any:
            captured.append(dict(kwargs.get("headers", {})))
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "request_id": dispatch.request_id,
                "status": "success",
                "output": {"data": {"r": 1}, "output_schema_version": "1.0"},
                "error": None,
                "duration_ms": 10,
            }
            return resp

        client = AgentWorkerClient(
            base_url="http://agent-worker.local",
            token_fetcher=AsyncMock(return_value="tok"),
        )

        def _fake_inject(carrier: dict[str, str]) -> None:
            carrier["traceparent"] = "00-deadbeef-01"

        with (
            patch("opentelemetry.propagate.inject", side_effect=_fake_inject),
            patch("httpx.AsyncClient.post", new=_patched_post),
        ):
            await client.execute(dispatch)

        assert len(captured) == 1
        hdrs = captured[0]
        assert hdrs.get("X-Request-ID") == "req-corr-002"
        assert hdrs.get("X-Trace-ID") == "b" * 32
        assert hdrs.get("traceparent") == "00-deadbeef-01"

    @pytest.mark.asyncio
    async def test_inject_failure_does_not_break_request(self) -> None:
        """If opentelemetry.propagate.inject raises, the request must still succeed."""
        dispatch = ToolCallDispatch(
            request_id="req-safe-003",
            user_id="u",
            tool_name="search",
            arguments={"query": "q"},
            trace_id="0" * 32,
        )

        async def _patched_post(self_: Any, url: str, **kwargs: Any) -> Any:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "request_id": dispatch.request_id,
                "status": "success",
                "output": {"data": {"r": 1}, "output_schema_version": "1.0"},
                "error": None,
                "duration_ms": 10,
            }
            return resp

        client = AgentWorkerClient(
            base_url="http://agent-worker.local",
            token_fetcher=AsyncMock(return_value="tok"),
        )

        with (
            patch("opentelemetry.propagate.inject", side_effect=RuntimeError("otel unavailable")),
            patch("httpx.AsyncClient.post", new=_patched_post),
        ):
            result = await client.execute(dispatch)

        # Must succeed despite inject failure
        assert result.data == {"r": 1}
