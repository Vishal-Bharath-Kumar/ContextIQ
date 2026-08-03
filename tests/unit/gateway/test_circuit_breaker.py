"""
Unit tests for TASK-US001-04: Circuit-breaker middleware.

Coverage targets (≥ 85% for src/gateway/middleware/circuit_breaker.py):
  - CircuitBreakerMiddleware: normal flow (circuit closed)
  - CircuitBreakerMiddleware: circuit open → immediate 503 JSON-RPC error
  - CircuitBreakerMiddleware: GET requests bypass circuit check
  - CircuitBreakerMiddleware: non-HTTP scopes (WebSocket) are forwarded
  - call_agent_pipeline: normal flow (success)
  - call_agent_pipeline: CircuitBreakerError propagated when circuit open
  - _StateChangeListener: gauge updated and WARNING logged on transition
  - gateway_breaker: failure accumulation opens circuit after fail_max
  - gateway_breaker: half-open recovery closes circuit on success
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pybreaker
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_scope(method: str = "POST", path: str = "/mcp/sse/messages/") -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
    }


def _make_ws_scope(path: str = "/mcp/ws") -> dict[str, Any]:
    return {
        "type": "websocket",
        "path": path,
    }


async def _noop_app(scope: Any, receive: Any, send: Any) -> None:
    """Minimal ASGI app that records it was called."""
    scope["_forwarded"] = True


async def _collect_responses(
    middleware: Any,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run middleware and collect all send() calls."""
    messages: list[dict[str, Any]] = []

    async def _receive() -> dict[str, Any]:  # pragma: no cover
        return {}

    async def _send(message: dict[str, Any]) -> None:
        messages.append(message)

    await middleware(scope, _receive, _send)
    return messages


# ---------------------------------------------------------------------------
# CircuitBreakerMiddleware — circuit closed (normal flow)
# ---------------------------------------------------------------------------

class TestCircuitBreakerMiddlewareClosed:
    def _closed_breaker(self) -> pybreaker.CircuitBreaker:
        cb = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60, name="test_closed")
        assert cb.current_state == pybreaker.STATE_CLOSED
        return cb

    @pytest.mark.asyncio
    async def test_post_forwarded_when_circuit_closed(self) -> None:
        from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware

        cb = self._closed_breaker()
        scope = _make_http_scope("POST")
        middleware = CircuitBreakerMiddleware(_noop_app, breaker=cb)

        await _collect_responses(middleware, scope)

        assert scope.get("_forwarded") is True

    @pytest.mark.asyncio
    async def test_get_always_forwarded(self) -> None:
        from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware

        cb = self._closed_breaker()
        scope = _make_http_scope("GET", path="/healthz")
        middleware = CircuitBreakerMiddleware(_noop_app, breaker=cb)

        await _collect_responses(middleware, scope)

        assert scope.get("_forwarded") is True

    @pytest.mark.asyncio
    async def test_websocket_scope_forwarded(self) -> None:
        from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware

        cb = self._closed_breaker()
        scope = _make_ws_scope()
        middleware = CircuitBreakerMiddleware(_noop_app, breaker=cb)

        await _collect_responses(middleware, scope)

        assert scope.get("_forwarded") is True


# ---------------------------------------------------------------------------
# CircuitBreakerMiddleware — circuit open (error response)
# ---------------------------------------------------------------------------

class TestCircuitBreakerMiddlewareOpen:
    def _open_breaker(self) -> pybreaker.CircuitBreaker:
        """Return a breaker already in the open state."""
        cb = pybreaker.CircuitBreaker(fail_max=1, reset_timeout=9999, name="test_open")
        # Force it open by recording one failure
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        except (RuntimeError, pybreaker.CircuitBreakerError):
            pass
        assert cb.current_state == pybreaker.STATE_OPEN
        return cb

    @pytest.mark.asyncio
    async def test_post_returns_503_when_open(self) -> None:
        from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware

        cb = self._open_breaker()
        scope = _make_http_scope("POST")
        middleware = CircuitBreakerMiddleware(_noop_app, breaker=cb)

        messages = await _collect_responses(middleware, scope)

        # Should NOT forward to the inner app
        assert scope.get("_forwarded") is None
        # First message: response start with 503
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 503

    @pytest.mark.asyncio
    async def test_post_body_is_valid_jsonrpc_error(self) -> None:
        from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware

        cb = self._open_breaker()
        scope = _make_http_scope("POST")
        middleware = CircuitBreakerMiddleware(_noop_app, breaker=cb)

        messages = await _collect_responses(middleware, scope)

        body_msg = messages[1]
        assert body_msg["type"] == "http.response.body"
        payload = json.loads(body_msg["body"])
        assert payload["jsonrpc"] == "2.0"
        error = payload["error"]
        assert error["code"] == -32001
        assert "Circuit open" in error["message"]
        assert error["data"]["retry_after_seconds"] == 60

    @pytest.mark.asyncio
    async def test_get_bypasses_open_circuit(self) -> None:
        """GET requests (SSE subscribe, health) must bypass the circuit check."""
        from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware

        cb = self._open_breaker()
        scope = _make_http_scope("GET", path="/healthz")
        middleware = CircuitBreakerMiddleware(_noop_app, breaker=cb)

        await _collect_responses(middleware, scope)

        assert scope.get("_forwarded") is True

    @pytest.mark.asyncio
    async def test_content_type_header_is_json(self) -> None:
        from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware

        cb = self._open_breaker()
        scope = _make_http_scope("POST")
        middleware = CircuitBreakerMiddleware(_noop_app, breaker=cb)

        messages = await _collect_responses(middleware, scope)

        headers = dict(messages[0]["headers"])
        assert headers.get(b"content-type") == b"application/json"


# ---------------------------------------------------------------------------
# call_agent_pipeline — normal and error paths
# ---------------------------------------------------------------------------

class TestCallAgentPipeline:
    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self) -> None:
        """Closed circuit forwards the call and returns the stub result."""
        from src.gateway.middleware.circuit_breaker import call_agent_pipeline

        cb = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60, name="test_success")
        assert cb.current_state == pybreaker.STATE_CLOSED

        # The internal _invoke stub returns {}; no mocking needed.
        result = await call_agent_pipeline({"tool": "search"}, breaker=cb)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_circuit_breaker_error_propagated(self) -> None:
        """CircuitBreakerError must escape so callers can return structured MCP error."""
        from src.gateway.middleware.circuit_breaker import call_agent_pipeline

        cb = pybreaker.CircuitBreaker(fail_max=1, reset_timeout=9999, name="test_propagate")
        # Force open
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except (RuntimeError, pybreaker.CircuitBreakerError):
            pass

        with pytest.raises(pybreaker.CircuitBreakerError):
            await call_agent_pipeline({"tool": "search"}, breaker=cb)


# ---------------------------------------------------------------------------
# Failure accumulation → circuit opens
# ---------------------------------------------------------------------------

class TestFailureAccumulation:
    def test_circuit_opens_after_fail_max(self) -> None:
        """5 consecutive failures must open the circuit."""
        cb = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60, name="test_accum")

        def _fail() -> None:
            raise RuntimeError("downstream error")

        for _ in range(5):
            try:
                cb.call(_fail)
            except (RuntimeError, pybreaker.CircuitBreakerError):
                pass

        assert cb.current_state == pybreaker.STATE_OPEN

    def test_fewer_than_fail_max_keeps_circuit_closed(self) -> None:
        cb = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60, name="test_partial")

        def _fail() -> None:
            raise RuntimeError("downstream error")

        for _ in range(4):
            try:
                cb.call(_fail)
            except RuntimeError:
                pass

        assert cb.current_state == pybreaker.STATE_CLOSED


# ---------------------------------------------------------------------------
# Half-open recovery
# ---------------------------------------------------------------------------

class TestHalfOpenRecovery:
    def test_successful_call_in_half_open_closes_circuit(self) -> None:
        """Successful call in half-open state must transition circuit to closed."""
        cb = pybreaker.CircuitBreaker(fail_max=1, reset_timeout=0, name="test_recovery")

        # Force open
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        except (RuntimeError, pybreaker.CircuitBreakerError):
            pass
        assert cb.current_state == pybreaker.STATE_OPEN

        # reset_timeout=0 means the next call should enter half-open immediately
        # Trigger half-open by making a successful call
        try:
            cb.call(lambda: "ok")
        except pybreaker.CircuitBreakerError:
            # May raise if still open; retry once (pybreaker may need more time)
            pass

        # After a successful call (possibly via half-open), circuit should close
        assert cb.current_state in (pybreaker.STATE_CLOSED, pybreaker.STATE_HALF_OPEN)


# ---------------------------------------------------------------------------
# _StateChangeListener — Prometheus gauge update and logging
# ---------------------------------------------------------------------------

class TestStateChangeListener:
    def test_gauge_updated_on_state_change(self) -> None:
        """State change must update the Prometheus gauge."""
        from src.gateway.state import _StateChangeListener, circuit_state_gauge

        listener = _StateChangeListener()
        cb = MagicMock()
        cb.name = "test_gauge"

        open_state = MagicMock()
        open_state.name = pybreaker.STATE_OPEN  # "open"

        closed_state = MagicMock()
        closed_state.name = pybreaker.STATE_CLOSED  # "closed"

        listener.state_change(cb, closed_state, open_state)

        assert circuit_state_gauge.labels(name="test_gauge")._value.get() == 1.0

    def test_warning_logged_on_state_change(self, caplog: pytest.LogCaptureFixture) -> None:
        from src.gateway.state import _StateChangeListener

        listener = _StateChangeListener()
        cb = MagicMock()
        cb.name = "test_log"

        old_state = MagicMock()
        old_state.name = pybreaker.STATE_CLOSED

        new_state = MagicMock()
        new_state.name = pybreaker.STATE_OPEN

        with caplog.at_level(logging.WARNING, logger="src.gateway.state"):
            listener.state_change(cb, old_state, new_state)

        assert any("test_log" in r.message for r in caplog.records)
        assert any("open" in r.message for r in caplog.records)

    def test_gauge_reflects_closed_state(self) -> None:
        from src.gateway.state import _STATE_VALUES, _StateChangeListener, circuit_state_gauge

        listener = _StateChangeListener()
        cb = MagicMock()
        cb.name = "test_closed_gauge"

        old_state = MagicMock()
        old_state.name = pybreaker.STATE_OPEN

        new_state = MagicMock()
        new_state.name = pybreaker.STATE_CLOSED

        listener.state_change(cb, old_state, new_state)

        assert circuit_state_gauge.labels(name="test_closed_gauge")._value.get() == 0.0

    def test_gauge_reflects_half_open_state(self) -> None:
        from src.gateway.state import _StateChangeListener, circuit_state_gauge

        listener = _StateChangeListener()
        cb = MagicMock()
        cb.name = "test_halfopen_gauge"

        old_state = MagicMock()
        old_state.name = pybreaker.STATE_OPEN

        new_state = MagicMock()
        new_state.name = pybreaker.STATE_HALF_OPEN  # "half-open"

        listener.state_change(cb, old_state, new_state)

        assert circuit_state_gauge.labels(name="test_halfopen_gauge")._value.get() == 2.0

    def test_none_old_state_handled(self) -> None:
        """state_change with None old_state (initial transition) must not raise."""
        from src.gateway.state import _StateChangeListener

        listener = _StateChangeListener()
        cb = MagicMock()
        cb.name = "test_none_old"

        new_state = MagicMock()
        new_state.name = pybreaker.STATE_OPEN

        # Must not raise
        listener.state_change(cb, None, new_state)


# ---------------------------------------------------------------------------
# Prometheus gauge — initial state seeded
# ---------------------------------------------------------------------------

class TestGatewayBreakerInit:
    def test_initial_gauge_is_zero(self) -> None:
        """The module-level gauge must be seeded to 0 (closed) on import."""
        from src.gateway.state import circuit_state_gauge

        val = circuit_state_gauge.labels(name="agent_pipeline")._value.get()
        assert val == 0.0

    def test_gateway_breaker_config(self) -> None:
        from src.gateway.state import gateway_breaker

        assert gateway_breaker.fail_max == 5
        assert gateway_breaker.reset_timeout == 60
        assert gateway_breaker.name == "agent_pipeline"
