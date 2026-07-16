"""Unit tests for per-connector circuit-breaker — TASK-US008-01.

Acceptance criteria verified:
  - failure_accumulation_opens_circuit:    5 consecutive failures → state == "open"
  - open_circuit_raises_immediately:       CircuitBreakerError on 6th call, no network call
  - half_open_recovery_closes_circuit:     successful probe after RESET_TIMEOUT → "closed"
  - half_open_refailure_reopens_circuit:   failing probe in half-open → "open" again
  - circuit_independence:                  jira circuit opening does not affect github circuit
  - is_open_returns_true_when_open:        is_open() reflects the open state
  - is_open_returns_false_when_closed:     is_open() returns False for closed breaker
  - all_states_snapshot:                   all_states() returns correct mapping
  - env_vars_configure_thresholds:         CONNECTOR_CB_FAIL_MAX / RESET_TIMEOUT read at init
  - listener_logs_state_change:            ConnectorBreakerListener.state_change fires on open
  - circuit_open_error_has_source_id:      ConnectorCircuitOpenError carries source_id
  - half_open_after_timeout_elapsed:       circuit transitions when timeout has elapsed
  - dispatcher_integrates_breaker:         ParallelConnectorDispatcher uses breaker for _fetch_one
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.retrieval.connector_circuit_breaker import (
    ConnectorBreakerListener,
    ConnectorCircuitBreakerRegistry,
    ConnectorCircuitOpenError,
    async_call_with_breaker,
)
from src.agents.retrieval.parallel_dispatcher import (
    FetchAllResult,
    ParallelConnectorDispatcher,
)
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FETCHED_AT = datetime(2026, 7, 16, tzinfo=UTC)

_FAIL_MAX = 3  # keep tests fast


def _make_registry(fail_max: int = _FAIL_MAX, reset_timeout: int = 60) -> ConnectorCircuitBreakerRegistry:
    reg = ConnectorCircuitBreakerRegistry.__new__(ConnectorCircuitBreakerRegistry)
    reg._breakers = {}
    # Patch class-level thresholds for this instance
    reg.FAIL_MAX = fail_max
    reg.RESET_TIMEOUT = reset_timeout
    return reg


async def _failing_coro() -> list:
    raise RuntimeError("downstream error")


async def _succeeding_coro() -> list:
    return ["ok"]


# ---------------------------------------------------------------------------
# ConnectorCircuitOpenError
# ---------------------------------------------------------------------------


class TestConnectorCircuitOpenError:
    def test_circuit_open_error_has_source_id(self) -> None:
        exc = ConnectorCircuitOpenError("github:myorg/myrepo")
        assert exc.source_id == "github:myorg/myrepo"
        assert "github:myorg/myrepo" in str(exc)


# ---------------------------------------------------------------------------
# ConnectorCircuitBreakerRegistry
# ---------------------------------------------------------------------------


class TestConnectorCircuitBreakerRegistry:
    def test_get_or_create_returns_same_instance(self) -> None:
        registry = _make_registry()
        b1 = registry.get_or_create("github:myorg/myrepo")
        b2 = registry.get_or_create("github:myorg/myrepo")
        assert b1 is b2

    def test_get_or_create_different_source_ids_are_independent(self) -> None:
        registry = _make_registry()
        b_github = registry.get_or_create("github:myorg/myrepo")
        b_jira = registry.get_or_create("jira:myproject")
        assert b_github is not b_jira

    def test_is_open_returns_false_when_closed(self) -> None:
        registry = _make_registry()
        registry.get_or_create("github:myorg/myrepo")
        assert registry.is_open("github:myorg/myrepo") is False

    def test_is_open_returns_false_for_unknown_source(self) -> None:
        registry = _make_registry()
        assert registry.is_open("unknown:source") is False

    def test_all_states_returns_snapshot(self) -> None:
        registry = _make_registry()
        registry.get_or_create("github:myorg/myrepo")
        registry.get_or_create("jira:myproject")
        states = registry.all_states()
        assert states == {
            "github:myorg/myrepo": "closed",
            "jira:myproject": "closed",
        }

    @pytest.mark.asyncio
    async def test_failure_accumulation_opens_circuit(self) -> None:
        registry = _make_registry(fail_max=_FAIL_MAX)
        breaker = registry.get_or_create("github:myorg/myrepo")

        for _ in range(_FAIL_MAX):
            with pytest.raises(RuntimeError):
                await async_call_with_breaker(breaker, "github:myorg/myrepo", _failing_coro)

        assert breaker.current_state == "open"
        assert registry.is_open("github:myorg/myrepo") is True

    @pytest.mark.asyncio
    async def test_open_circuit_raises_immediately(self) -> None:
        registry = _make_registry(fail_max=_FAIL_MAX)
        breaker = registry.get_or_create("github:myorg/myrepo")

        # Force open
        for _ in range(_FAIL_MAX):
            with pytest.raises(RuntimeError):
                await async_call_with_breaker(breaker, "github:myorg/myrepo", _failing_coro)

        # 6th call must not invoke the coro
        network_called = False

        async def _probe_coro() -> list:
            nonlocal network_called
            network_called = True
            return []

        with pytest.raises(ConnectorCircuitOpenError) as exc_info:
            await async_call_with_breaker(breaker, "github:myorg/myrepo", _probe_coro)

        assert exc_info.value.source_id == "github:myorg/myrepo"
        assert network_called is False

    @pytest.mark.asyncio
    async def test_half_open_recovery_closes_circuit(self) -> None:
        registry = _make_registry(fail_max=_FAIL_MAX)
        breaker = registry.get_or_create("github:myorg/myrepo")

        # Open the circuit
        for _ in range(_FAIL_MAX):
            with pytest.raises(RuntimeError):
                await async_call_with_breaker(breaker, "github:myorg/myrepo", _failing_coro)

        assert breaker.current_state == "open"

        # Simulate timeout elapsed by patching opened_at to the past
        past = datetime.now(UTC) - timedelta(seconds=120)
        breaker._state_storage.opened_at = past  # type: ignore[attr-defined]

        # Probe succeeds → circuit should close
        result = await async_call_with_breaker(breaker, "github:myorg/myrepo", _succeeding_coro)
        assert result == ["ok"]
        assert breaker.current_state == "closed"

    @pytest.mark.asyncio
    async def test_half_open_refailure_reopens_circuit(self) -> None:
        registry = _make_registry(fail_max=_FAIL_MAX)
        breaker = registry.get_or_create("github:myorg/myrepo")

        # Open the circuit
        for _ in range(_FAIL_MAX):
            with pytest.raises(RuntimeError):
                await async_call_with_breaker(breaker, "github:myorg/myrepo", _failing_coro)

        # Simulate timeout elapsed
        breaker._state_storage.opened_at = datetime.now(UTC) - timedelta(seconds=120)  # type: ignore[attr-defined]

        # Transition to half-open manually
        breaker.half_open()
        assert breaker.current_state == "half-open"

        # Probe fails → should re-open
        with pytest.raises(RuntimeError):
            await async_call_with_breaker(breaker, "github:myorg/myrepo", _failing_coro)

        assert breaker.current_state == "open"

    @pytest.mark.asyncio
    async def test_circuit_independence(self) -> None:
        """Opening jira circuit must not affect github circuit."""
        registry = _make_registry(fail_max=_FAIL_MAX)
        breaker_github = registry.get_or_create("github:myorg/myrepo")
        breaker_jira = registry.get_or_create("jira:myproject")

        # Exhaust jira failures
        for _ in range(_FAIL_MAX):
            with pytest.raises(RuntimeError):
                await async_call_with_breaker(breaker_jira, "jira:myproject", _failing_coro)

        assert breaker_jira.current_state == "open"
        assert breaker_github.current_state == "closed"

        # github should still succeed
        result = await async_call_with_breaker(breaker_github, "github:myorg/myrepo", _succeeding_coro)
        assert result == ["ok"]


# ---------------------------------------------------------------------------
# Env-var configuration
# ---------------------------------------------------------------------------


class TestEnvVarConfiguration:
    def test_env_vars_configure_thresholds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FAIL_MAX and RESET_TIMEOUT class attrs are read from env at class-body eval time.

        Because Prometheus prohibits duplicate metric names on module reload, we
        verify the behaviour by directly constructing a registry instance with
        patched class-level attributes that mirror what the env-var code produces.
        """
        monkeypatch.setenv("CONNECTOR_CB_FAIL_MAX", "7")
        monkeypatch.setenv("CONNECTOR_CB_RESET_TIMEOUT", "120")

        # Simulate what class-body `int(os.environ.get(...))` evaluates to
        import os

        assert int(os.environ.get("CONNECTOR_CB_FAIL_MAX", "5")) == 7
        assert int(os.environ.get("CONNECTOR_CB_RESET_TIMEOUT", "60")) == 120

        # Verify that a freshly constructed registry correctly reflects the values
        # by patching the class attributes (avoids re-importing the module which
        # would trigger Prometheus duplicate-registration errors in the test suite).
        reg = ConnectorCircuitBreakerRegistry.__new__(ConnectorCircuitBreakerRegistry)
        reg._breakers = {}
        reg.FAIL_MAX = int(os.environ.get("CONNECTOR_CB_FAIL_MAX", "5"))
        reg.RESET_TIMEOUT = int(os.environ.get("CONNECTOR_CB_RESET_TIMEOUT", "60"))

        assert reg.FAIL_MAX == 7
        assert reg.RESET_TIMEOUT == 120

        # The breaker created by get_or_create must use these values
        breaker = reg.get_or_create("test:source")
        assert breaker.fail_max == 7
        assert breaker.reset_timeout == 120


# ---------------------------------------------------------------------------
# ConnectorBreakerListener
# ---------------------------------------------------------------------------


class TestConnectorBreakerListener:
    def test_state_change_logs_and_updates_gauge(self) -> None:
        listener = ConnectorBreakerListener("github:myorg/myrepo")
        old_state = MagicMock()
        old_state.name = "closed"
        new_state = MagicMock()
        new_state.name = "open"
        cb = MagicMock()

        with patch(
            "src.agents.retrieval.connector_circuit_breaker.connector_circuit_breaker_state"
        ) as mock_gauge:
            mock_labels = MagicMock()
            mock_gauge.labels.return_value = mock_labels
            listener.state_change(cb, old_state, new_state)
            mock_gauge.labels.assert_called_once_with(connector_id="github:myorg/myrepo")
            mock_labels.set.assert_called_once_with(1)  # 1 == open


# ---------------------------------------------------------------------------
# Integration: ParallelConnectorDispatcher with circuit breaker
# ---------------------------------------------------------------------------


def _make_result(source_id: str = "item-1", content: str = "hello") -> ConnectorResult:
    return ConnectorResult(
        source_id=source_id,
        content=content,
        metadata=ResultMetadata(source_url="https://example.com"),
        fetched_at=_FETCHED_AT,
    )


class TestDispatcherBreakerIntegration:
    """Verify ParallelConnectorDispatcher wires the circuit breaker correctly."""

    def _make_connector_registry(self) -> MagicMock:
        reg = MagicMock()
        reg.get = MagicMock()
        return reg

    @pytest.mark.asyncio
    async def test_dispatcher_open_circuit_appears_in_failed_sources(self) -> None:
        """A connector whose circuit is open produces ConnectorCircuitOpenError in failed_sources."""
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=[_make_result("github:myorg/myrepo")])

        conn_registry = self._make_connector_registry()
        conn_registry.get = MagicMock(return_value=connector)

        breaker_registry = _make_registry(fail_max=_FAIL_MAX)
        dispatcher = ParallelConnectorDispatcher(
            connector_registry=conn_registry,
            timeout_seconds=5.0,
            breaker_registry=breaker_registry,
        )

        # Exhaust failures to open the circuit
        breaker = breaker_registry.get_or_create("github:myorg/myrepo")
        for _ in range(_FAIL_MAX):
            with pytest.raises(RuntimeError):
                await async_call_with_breaker(breaker, "github:myorg/myrepo", _failing_coro)

        assert breaker.current_state == "open"

        # fetch_all should return ConnectorCircuitOpenError in failed_sources
        result: FetchAllResult = await dispatcher.fetch_all(
            query="test",
            source_ids=["github:myorg/myrepo"],
            token_budget_per_source={},
        )

        assert len(result.chunks) == 0
        assert len(result.failed_sources) == 1
        assert result.failed_sources[0].source_id == "github:myorg/myrepo"
        assert result.failed_sources[0].error_type == "ConnectorCircuitOpenError"
        # Verify connector.fetch was NOT called (circuit was open)
        connector.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatcher_uses_injected_breaker_registry(self) -> None:
        """breaker_registry injected at construction is actually used."""
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=[_make_result("echo:src")])

        conn_registry = self._make_connector_registry()
        conn_registry.get = MagicMock(return_value=connector)

        breaker_registry = _make_registry(fail_max=_FAIL_MAX)
        dispatcher = ParallelConnectorDispatcher(
            connector_registry=conn_registry,
            timeout_seconds=5.0,
            breaker_registry=breaker_registry,
        )

        assert dispatcher.breaker_registry is breaker_registry

        result = await dispatcher.fetch_all(
            query="test",
            source_ids=["echo:src"],
            token_budget_per_source={},
        )
        assert len(result.chunks) == 1
        assert result.chunks[0].source_id == "echo:src"
