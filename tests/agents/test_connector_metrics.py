"""Unit tests for consolidated connector metrics — TASK-US008-04.

Acceptance criteria verified:
  - failure_count_timeout:            connector_failure_count{failure_type="timeout"} increments
  - failure_count_error:              connector_failure_count{failure_type="error"} increments
  - failure_count_circuit_open:       connector_failure_count{failure_type="circuit_open"} increments
  - gauge_zero_at_startup:            connector_circuit_breaker_state == 0 (closed) after register()
  - gauge_one_when_open:              connector_circuit_breaker_state == 1 when circuit transitions open
  - structured_log_on_state_change:   connector_circuit_state_change log emitted with from/to fields
  - no_duplicate_metric_definitions:  metrics.py is the sole definition source
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.retrieval.connector_circuit_breaker import (
    ConnectorBreakerListener,
    ConnectorCircuitBreakerRegistry,
)
from src.agents.retrieval.connector_registry import ConnectorRegistry
from src.agents.retrieval.parallel_dispatcher import (
    ConnectorTimeoutError,
    ParallelConnectorDispatcher,
)
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FETCHED_AT = datetime(2026, 7, 16, tzinfo=UTC)


def _make_result(source_id: str = "item-1", content: str = "hello") -> ConnectorResult:
    return ConnectorResult(
        source_id=source_id,
        content=content,
        metadata=ResultMetadata(source_url="https://example.com"),
        fetched_at=_FETCHED_AT,
    )


def _fast_connector(source_id: str = "echo:fast") -> MagicMock:
    connector = MagicMock()
    connector.fetch = AsyncMock(return_value=[_make_result(source_id)])
    return connector


def _slow_connector(delay: float = 10.0) -> MagicMock:
    async def _slow_fetch(_query):  # type: ignore[no-untyped-def]
        await asyncio.sleep(delay)
        return []  # pragma: no cover

    connector = MagicMock()
    connector.fetch = AsyncMock(side_effect=_slow_fetch)
    return connector


def _error_connector(exc: Exception) -> MagicMock:
    connector = MagicMock()
    connector.fetch = AsyncMock(side_effect=exc)
    return connector


def _read_counter(metric: object, labels: dict) -> float:
    from prometheus_client import REGISTRY

    name = metric._name  # type: ignore[attr-defined]
    return REGISTRY.get_sample_value(name + "_total", labels) or 0.0


def _read_gauge(metric: object, labels: dict) -> float:
    from prometheus_client import REGISTRY

    name = metric._name  # type: ignore[attr-defined]
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ---------------------------------------------------------------------------
# connector_failure_count — timeout
# ---------------------------------------------------------------------------


class TestFailureCountTimeout:
    @pytest.mark.asyncio
    async def test_failure_count_timeout_increments(self) -> None:
        from src.agents.retrieval.metrics import connector_failure_count

        slow = _slow_connector(delay=10.0)
        dispatcher = ParallelConnectorDispatcher(connector_registry=MagicMock())

        before = _read_counter(
            connector_failure_count,
            {"connector_id": "jira:myproject", "failure_type": "timeout"},
        )

        with pytest.raises(ConnectorTimeoutError):
            await dispatcher._fetch_one(
                source_id="jira:myproject",
                connector=slow,
                query="sprint goals",
                token_budget=None,
            )

        after = _read_counter(
            connector_failure_count,
            {"connector_id": "jira:myproject", "failure_type": "timeout"},
        )
        assert after - before == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# connector_failure_count — error
# ---------------------------------------------------------------------------


class TestFailureCountError:
    @pytest.mark.asyncio
    async def test_failure_count_error_increments(self) -> None:
        from src.agents.retrieval.metrics import connector_failure_count

        bad = _error_connector(RuntimeError("upstream error"))
        dispatcher = ParallelConnectorDispatcher(connector_registry=MagicMock())

        before = _read_counter(
            connector_failure_count,
            {"connector_id": "github:org/repo", "failure_type": "error"},
        )

        with pytest.raises(RuntimeError):
            await dispatcher._fetch_one(
                source_id="github:org/repo",
                connector=bad,
                query="open PRs",
                token_budget=None,
            )

        after = _read_counter(
            connector_failure_count,
            {"connector_id": "github:org/repo", "failure_type": "error"},
        )
        assert after - before == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# connector_failure_count — circuit_open
# ---------------------------------------------------------------------------


class TestFailureCountCircuitOpen:
    @pytest.mark.asyncio
    async def test_failure_count_circuit_open_increments(self) -> None:
        from src.agents.retrieval.metrics import connector_failure_count

        source_id = "jira:circuit-open-test"
        connector = _fast_connector(source_id)
        breaker_registry = MagicMock(spec=ConnectorCircuitBreakerRegistry)
        breaker_registry.is_open.return_value = True

        conn_registry = MagicMock()
        conn_registry.get.return_value = connector

        dispatcher = ParallelConnectorDispatcher(
            connector_registry=conn_registry,
            breaker_registry=breaker_registry,
        )

        before = _read_counter(
            connector_failure_count,
            {"connector_id": source_id, "failure_type": "circuit_open"},
        )

        result = await dispatcher.fetch_all(
            query="test",
            source_ids=[source_id],
            token_budget_per_source={},
        )

        after = _read_counter(
            connector_failure_count,
            {"connector_id": source_id, "failure_type": "circuit_open"},
        )
        assert after - before == pytest.approx(1.0)
        assert result.chunks == []
        assert result.failed_sources[0].source_id == source_id


# ---------------------------------------------------------------------------
# connector_circuit_breaker_state — startup (gauge == 0)
# ---------------------------------------------------------------------------


class TestGaugeZeroAtStartup:
    def test_gauge_initialised_to_closed_on_register(self) -> None:
        from src.agents.retrieval.metrics import connector_circuit_breaker_state

        source_id = "echo:gauge-init-test"
        connector = MagicMock()

        registry = ConnectorRegistry()
        registry.register(source_id, connector)

        value = _read_gauge(
            connector_circuit_breaker_state,
            {"connector_id": source_id},
        )
        assert value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# connector_circuit_breaker_state — gauge == 1 when open
# ---------------------------------------------------------------------------


class TestGaugeOneWhenOpen:
    def test_gauge_set_to_one_on_open_transition(self) -> None:
        from src.agents.retrieval.metrics import connector_circuit_breaker_state

        source_id = "jira:gauge-open-test"
        listener = ConnectorBreakerListener(source_id)

        old_state = MagicMock()
        old_state.name = "closed"
        new_state = MagicMock()
        new_state.name = "open"
        cb = MagicMock()
        cb.fail_max = 5
        cb.reset_timeout = 60

        listener.state_change(cb, old_state, new_state)

        value = _read_gauge(
            connector_circuit_breaker_state,
            {"connector_id": source_id},
        )
        assert value == pytest.approx(1.0)

    def test_gauge_returns_to_zero_on_close_transition(self) -> None:
        from src.agents.retrieval.metrics import connector_circuit_breaker_state

        source_id = "jira:gauge-close-test"
        listener = ConnectorBreakerListener(source_id)
        cb = MagicMock()
        cb.fail_max = 5
        cb.reset_timeout = 60

        open_state = MagicMock()
        open_state.name = "closed"
        closed_state = MagicMock()
        closed_state.name = "open"
        listener.state_change(cb, open_state, closed_state)

        old_state = MagicMock()
        old_state.name = "open"
        new_state = MagicMock()
        new_state.name = "closed"
        listener.state_change(cb, old_state, new_state)

        value = _read_gauge(
            connector_circuit_breaker_state,
            {"connector_id": source_id},
        )
        assert value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Structured log on state transition
# ---------------------------------------------------------------------------


class TestStructuredLogOnStateChange:
    def test_structured_log_emitted_on_state_change(self) -> None:
        source_id = "confluence:log-test"
        listener = ConnectorBreakerListener(source_id)

        old_state = MagicMock()
        old_state.name = "closed"
        new_state = MagicMock()
        new_state.name = "open"
        cb = MagicMock()
        cb.fail_max = 5
        cb.reset_timeout = 60

        with patch(
            "src.agents.retrieval.connector_circuit_breaker._logger"
        ) as mock_logger:
            listener.state_change(cb, old_state, new_state)
            mock_logger.warning.assert_called_once()
            call_kwargs = mock_logger.warning.call_args
            assert call_kwargs[0][0] == "connector_circuit_state_change"
            assert call_kwargs[1]["connector_id"] == source_id
            assert call_kwargs[1]["from_state"] == "closed"
            assert call_kwargs[1]["to_state"] == "open"
            assert call_kwargs[1]["fail_max"] == cb.fail_max
            assert call_kwargs[1]["reset_timeout"] == cb.reset_timeout


# ---------------------------------------------------------------------------
# No duplicate metric definitions
# ---------------------------------------------------------------------------


class TestNoDuplicateMetricDefinitions:
    def test_metrics_module_is_single_source(self) -> None:
        """connector_circuit_breaker.py must not define its own gauge."""
        import importlib
        import inspect

        import src.agents.retrieval.connector_circuit_breaker as cb_module
        from prometheus_client import Gauge

        module_source = inspect.getsource(cb_module)
        # The module must not instantiate a new Gauge — it should only import
        assert 'Gauge(' not in module_source

    def test_connector_failure_count_is_in_metrics(self) -> None:
        from src.agents.retrieval import metrics

        assert hasattr(metrics, "connector_failure_count")

    def test_connector_circuit_breaker_state_is_in_metrics(self) -> None:
        from src.agents.retrieval import metrics

        assert hasattr(metrics, "connector_circuit_breaker_state")

    def test_old_metrics_removed(self) -> None:
        from src.agents.retrieval import metrics

        assert not hasattr(metrics, "connector_timeouts_total")
        assert not hasattr(metrics, "connector_errors_total")
        assert not hasattr(metrics, "connector_circuit_skip_total")
