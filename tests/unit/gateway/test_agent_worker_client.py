"""
Unit tests for TASK-US003-02: AgentWorkerClient HTTP client.

Coverage targets (≥ 85% on clients/agent_worker_client.py):
  - Successful execute: returns ToolCallOutput with correct data
  - X-Request-ID and X-Trace-ID headers present on every outbound request
  - Authorization Bearer header injected from service token
  - HTTP timeout raises McpError(INTERNAL_ERROR) with timeout_ms detail
  - Agent Worker HTTP 5xx raises McpError(INTERNAL_ERROR) with status code
  - Service token cached for 4 minutes (fetch_fn called only once)
  - Token cache refreshed after TTL expiry
  - Agent Worker returns status=error with output=None raises McpError
  - Output schema validation: violation logs WARNING and increments metric
  - Output schema validation: compliant payload passes silently
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

from src.gateway.clients.agent_worker_client import (
    AgentWorkerClient,
    _ServiceTokenCache,
)
from src.gateway.schemas.call_types import ToolCallDispatch, ToolCallOutput

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_DISPATCH = ToolCallDispatch(
    request_id="req-abc-123",
    user_id="user-xyz",
    tool_name="search",
    arguments={"query": "hello"},
    trace_id="a" * 32,
)

_SUCCESS_RESPONSE = {
    "request_id": "req-abc-123",
    "status": "success",
    "output": {"data": {"results": ["a", "b"]}, "output_schema_version": "1.0"},
    "error": None,
    "duration_ms": 120,
}


def _make_client(
    base_url: str = "http://test-worker",
    timeout: float = 5.0,
    token: str = "mock-token",
) -> AgentWorkerClient:
    """Return a client with an injectable mock token fetcher."""
    async def _fetch_token() -> str:
        return token

    return AgentWorkerClient(
        base_url=base_url,
        timeout_seconds=timeout,
        token_fetcher=_fetch_token,
    )


# ---------------------------------------------------------------------------
# _ServiceTokenCache tests
# ---------------------------------------------------------------------------

class TestServiceTokenCache:
    @pytest.mark.asyncio
    async def test_calls_fetch_on_first_get(self) -> None:
        cache = _ServiceTokenCache(ttl_seconds=60.0)
        fetch = AsyncMock(return_value="token-1")

        result = await cache.get(fetch)

        assert result == "token-1"
        fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caches_token_within_ttl(self) -> None:
        cache = _ServiceTokenCache(ttl_seconds=60.0)
        fetch = AsyncMock(return_value="token-1")

        await cache.get(fetch)
        await cache.get(fetch)
        await cache.get(fetch)

        fetch.assert_awaited_once()  # Only one real fetch call.

    @pytest.mark.asyncio
    async def test_refreshes_after_ttl_expiry(self) -> None:
        cache = _ServiceTokenCache(ttl_seconds=10.0)
        fetch = AsyncMock(side_effect=["token-1", "token-2"])

        await cache.get(fetch)

        # Manually expire the cache by setting expires_at to the past.
        cache._expires_at = time.monotonic() - 1.0

        result = await cache.get(fetch)

        assert result == "token-2"
        assert fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_four_minute_ttl_default(self) -> None:
        cache = _ServiceTokenCache()
        assert cache._ttl == 240.0  # 4 minutes


# ---------------------------------------------------------------------------
# AgentWorkerClient.execute success path
# ---------------------------------------------------------------------------

class TestAgentWorkerClientSuccess:
    @pytest.mark.asyncio
    async def test_returns_tool_call_output(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json=_SUCCESS_RESPONSE,
            status_code=200,
        )
        client = _make_client()

        result = await client.execute(_SAMPLE_DISPATCH)

        assert isinstance(result, ToolCallOutput)
        assert result.data == {"results": ["a", "b"]}
        assert result.output_schema_version == "1.0"

    @pytest.mark.asyncio
    async def test_request_id_header_present(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json=_SUCCESS_RESPONSE,
            status_code=200,
        )
        client = _make_client()

        await client.execute(_SAMPLE_DISPATCH)

        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        assert requests[0].headers["X-Request-ID"] == "req-abc-123"

    @pytest.mark.asyncio
    async def test_trace_id_header_present(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json=_SUCCESS_RESPONSE,
            status_code=200,
        )
        client = _make_client()

        await client.execute(_SAMPLE_DISPATCH)

        requests = httpx_mock.get_requests()
        assert requests[0].headers["X-Trace-ID"] == "a" * 32

    @pytest.mark.asyncio
    async def test_authorization_bearer_header_injected(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json=_SUCCESS_RESPONSE,
            status_code=200,
        )
        client = _make_client(token="svc-jwt-token")

        await client.execute(_SAMPLE_DISPATCH)

        requests = httpx_mock.get_requests()
        assert requests[0].headers["Authorization"] == "Bearer svc-jwt-token"

    @pytest.mark.asyncio
    async def test_service_token_fetched_once_across_calls(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json=_SUCCESS_RESPONSE,
            status_code=200,
        )
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json=_SUCCESS_RESPONSE,
            status_code=200,
        )
        fetch_call_count = 0

        async def _counting_fetcher() -> str:
            nonlocal fetch_call_count
            fetch_call_count += 1
            return "cached-token"

        client = AgentWorkerClient(
            base_url="http://test-worker",
            timeout_seconds=5.0,
            token_fetcher=_counting_fetcher,
        )

        await client.execute(_SAMPLE_DISPATCH)
        await client.execute(_SAMPLE_DISPATCH)

        assert fetch_call_count == 1, "Token fetcher should be called only once within TTL."

    @pytest.mark.asyncio
    async def test_dispatch_payload_sent_as_json(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json=_SUCCESS_RESPONSE,
            status_code=200,
        )
        client = _make_client()

        await client.execute(_SAMPLE_DISPATCH)

        import json
        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["tool_name"] == "search"
        assert body["request_id"] == "req-abc-123"


# ---------------------------------------------------------------------------
# AgentWorkerClient.execute error paths
# ---------------------------------------------------------------------------

class TestAgentWorkerClientErrors:
    @pytest.mark.asyncio
    async def test_timeout_raises_mcp_error_with_timeout_ms(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"), url="http://test-worker/v1/execute")
        client = _make_client(timeout=5.0)

        from mcp.shared.exceptions import McpError
        from mcp.types import INTERNAL_ERROR

        with pytest.raises(McpError) as exc_info:
            await client.execute(_SAMPLE_DISPATCH)

        err = exc_info.value
        assert err.error.code == INTERNAL_ERROR
        assert "timed out" in err.error.message.lower()
        assert err.error.data == {"timeout_ms": 5000}

    @pytest.mark.asyncio
    async def test_http_500_raises_mcp_error_with_status_code(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            status_code=500,
        )
        client = _make_client()

        from mcp.shared.exceptions import McpError
        from mcp.types import INTERNAL_ERROR

        with pytest.raises(McpError) as exc_info:
            await client.execute(_SAMPLE_DISPATCH)

        err = exc_info.value
        assert err.error.code == INTERNAL_ERROR
        assert "500" in err.error.message

    @pytest.mark.asyncio
    async def test_http_503_raises_mcp_error_with_status_code(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            status_code=503,
        )
        client = _make_client()

        from mcp.shared.exceptions import McpError

        with pytest.raises(McpError) as exc_info:
            await client.execute(_SAMPLE_DISPATCH)

        assert "503" in exc_info.value.error.message

    @pytest.mark.asyncio
    async def test_empty_output_raises_mcp_error(self, httpx_mock: pytest.fixture) -> None:  # type: ignore[valid-type]
        httpx_mock.add_response(
            method="POST",
            url="http://test-worker/v1/execute",
            json={
                "request_id": "req-abc-123",
                "status": "error",
                "output": None,
                "error": {"code": "EXEC_FAILED", "message": "execution failed", "details": None},
                "duration_ms": 10,
            },
            status_code=200,
        )
        client = _make_client()

        from mcp.shared.exceptions import McpError

        with pytest.raises(McpError) as exc_info:
            await client.execute(_SAMPLE_DISPATCH)

        assert "empty output" in exc_info.value.error.message.lower()


# ---------------------------------------------------------------------------
# _ServiceTokenCache: 4-minute TTL enforcement (unit-level)
# ---------------------------------------------------------------------------

class TestServiceTokenCacheTTL:
    @pytest.mark.asyncio
    async def test_monotonic_expiry_triggers_refresh(self) -> None:
        """Simulate TTL expiry by patching time.monotonic."""
        cache = _ServiceTokenCache(ttl_seconds=10.0)
        fetch = AsyncMock(side_effect=["first-token", "second-token"])

        # First call — populates cache.
        token1 = await cache.get(fetch)
        assert token1 == "first-token"

        # Manually expire the cache by setting expires_at to the past.
        cache._expires_at = time.monotonic() - 1.0

        token2 = await cache.get(fetch)
        assert token2 == "second-token"
        assert fetch.await_count == 2
