"""Unit tests for per-connector timeout enforcement — TASK-US007-02.

Acceptance criteria verified:
  - timeout_fires:            connector that sleeps > timeout raises ConnectorTimeoutError
  - other_connectors_succeed: one timeout leaves other connectors' chunks intact
  - timeout_in_failed_sources: timed-out connector appears in failed_sources with
                                error_type == "ConnectorTimeoutError"
  - per_source_override:      grafana connector times out at 3 s, not default 5 s
  - global_env_override:      CONNECTOR_TIMEOUT_SECONDS env var changes DEFAULT_TIMEOUT
  - timeout_counter_increments: connector_failure_count{failure_type="timeout"} increments on timeout
  - error_counter_increments:   connector_failure_count{failure_type="error"} increments on error
  - success_duration_observed:  connector_fetch_duration success label is observed
  - elapsed_within_budget:      four connectors (one timing out) complete within
                                 timeout + 200 ms overhead
"""
from __future__ import annotations

import asyncio
import importlib
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.retrieval.parallel_dispatcher import (
    ConnectorTimeoutError,
    ContextChunk,
    FailedSource,
    FetchAllResult,
    ParallelConnectorDispatcher,
)
from src.agents.retrieval.timeout_config import (
    DEFAULT_TIMEOUT,
    CONNECTOR_TIMEOUT_OVERRIDES,
    get_connector_timeout,
)
from src.connector_sdk.schemas.query import ConnectorQuery
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
    """Connector that returns one result immediately."""
    connector = MagicMock()
    connector.fetch = AsyncMock(return_value=[_make_result(source_id)])
    return connector


def _slow_connector(delay: float = 10.0) -> MagicMock:
    """Connector that sleeps longer than any test timeout."""

    async def _slow_fetch(_query: ConnectorQuery) -> list[ConnectorResult]:
        await asyncio.sleep(delay)
        return []  # pragma: no cover

    connector = MagicMock()
    connector.fetch = AsyncMock(side_effect=_slow_fetch)
    return connector


def _error_connector(exc: Exception) -> MagicMock:
    connector = MagicMock()
    connector.fetch = AsyncMock(side_effect=exc)
    return connector


def _make_registry(source_map: dict) -> MagicMock:
    registry = MagicMock()
    registry.get.side_effect = lambda src: source_map.get(src)
    return registry


# ---------------------------------------------------------------------------
# timeout_config unit tests
# ---------------------------------------------------------------------------


class TestTimeoutConfig:
    def test_grafana_override(self) -> None:
        assert get_connector_timeout("grafana:dashboard") == 3.0

    def test_github_override(self) -> None:
        assert get_connector_timeout("github:org/repo") == 8.0

    def test_confluence_override(self) -> None:
        assert get_connector_timeout("confluence:space") == 5.0

    def test_jira_override(self) -> None:
        assert get_connector_timeout("jira:project") == 5.0

    def test_unknown_type_returns_default(self) -> None:
        assert get_connector_timeout("unknown:source") == DEFAULT_TIMEOUT

    def test_source_id_without_colon(self) -> None:
        """source_id with no colon falls through to unknown type → default."""
        assert get_connector_timeout("plain-source") == DEFAULT_TIMEOUT

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CONNECTOR_TIMEOUT_SECONDS env var changes DEFAULT_TIMEOUT at import time."""
        monkeypatch.setenv("CONNECTOR_TIMEOUT_SECONDS", "7.5")
        import src.agents.retrieval.timeout_config as tc_module

        importlib.reload(tc_module)
        assert tc_module.DEFAULT_TIMEOUT == pytest.approx(7.5)
        # Restore for other tests
        importlib.reload(tc_module)

    def test_all_overrides_positive(self) -> None:
        for connector_type, timeout in CONNECTOR_TIMEOUT_OVERRIDES.items():
            assert timeout > 0, f"{connector_type} timeout must be positive"


# ---------------------------------------------------------------------------
# ConnectorTimeoutError
# ---------------------------------------------------------------------------


class TestConnectorTimeoutError:
    def test_message(self) -> None:
        err = ConnectorTimeoutError(source_id="github:org/repo", timeout_seconds=8.0)
        assert "github:org/repo" in str(err)
        assert "8.0" in str(err)

    def test_attributes(self) -> None:
        err = ConnectorTimeoutError(source_id="grafana:dash", timeout_seconds=3.0)
        assert err.source_id == "grafana:dash"
        assert err.timeout_seconds == pytest.approx(3.0)

    def test_is_exception(self) -> None:
        err = ConnectorTimeoutError("x", 1.0)
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# _fetch_one — per-connector timeout and metrics
# ---------------------------------------------------------------------------


class TestFetchOneTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_connector_timeout_error(self) -> None:
        """A connector that sleeps past its timeout raises ConnectorTimeoutError."""
        slow = _slow_connector(delay=10.0)
        registry = _make_registry({"grafana:dash": slow})
        dispatcher = ParallelConnectorDispatcher(connector_registry=registry)

        with pytest.raises(ConnectorTimeoutError) as exc_info:
            await dispatcher._fetch_one(
                source_id="grafana:dash",
                connector=slow,
                query="cpu usage",
                token_budget=None,
            )

        assert exc_info.value.source_id == "grafana:dash"
        assert exc_info.value.timeout_seconds == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_grafana_timeout_is_3s_not_5s(self) -> None:
        """grafana connector uses its 3 s override, not the 5 s default."""
        slow = _slow_connector(delay=4.0)  # would pass 3 s but not 5 s threshold
        dispatcher = ParallelConnectorDispatcher(connector_registry=MagicMock())

        t0 = time.monotonic()
        with pytest.raises(ConnectorTimeoutError) as exc_info:
            await dispatcher._fetch_one(
                source_id="grafana:metrics",
                connector=slow,
                query="cpu",
                token_budget=None,
            )
        elapsed = time.monotonic() - t0

        assert exc_info.value.timeout_seconds == pytest.approx(3.0)
        # Should have timed out well before 5 s
        assert elapsed < 4.5, f"elapsed {elapsed:.2f}s exceeds 3 s override + buffer"

    @pytest.mark.asyncio
    async def test_success_returns_fetch_result(self) -> None:
        fast = _fast_connector("echo:fast")
        dispatcher = ParallelConnectorDispatcher(connector_registry=MagicMock())

        result = await dispatcher._fetch_one(
            source_id="echo:fast",
            connector=fast,
            query="test",
            token_budget=100,
        )

        assert result.source_id == "echo:fast"
        assert len(result.chunks) == 1
        assert result.chunks[0].content == "hello"


# ---------------------------------------------------------------------------
# fetch_all — partial results when one connector times out
# ---------------------------------------------------------------------------


class TestFetchAllWithTimeout:
    @pytest.mark.asyncio
    async def test_one_timeout_others_succeed(self) -> None:
        """One timed-out connector does not cancel the other three."""
        connectors = {
            "echo:c1": _fast_connector("echo:c1"),
            "echo:c2": _fast_connector("echo:c2"),
            "echo:c3": _fast_connector("echo:c3"),
            "grafana:dash": _slow_connector(delay=10.0),
        }
        registry = _make_registry(connectors)
        dispatcher = ParallelConnectorDispatcher(connector_registry=registry)

        result = await dispatcher.fetch_all(
            query="test query",
            source_ids=list(connectors.keys()),
            token_budget_per_source={},
        )

        assert isinstance(result, FetchAllResult)
        assert len(result.failed_sources) == 1
        assert result.failed_sources[0].source_id == "grafana:dash"
        assert result.failed_sources[0].error_type == "ConnectorTimeoutError"
        assert len(result.chunks) == 3

    @pytest.mark.asyncio
    async def test_timeout_recorded_in_failed_sources(self) -> None:
        connectors = {
            "github:org/repo": _slow_connector(delay=10.0),
        }
        registry = _make_registry(connectors)
        dispatcher = ParallelConnectorDispatcher(connector_registry=registry)

        result = await dispatcher.fetch_all(
            query="auth flow",
            source_ids=["github:org/repo"],
            token_budget_per_source={},
        )

        assert len(result.failed_sources) == 1
        fs = result.failed_sources[0]
        assert fs.source_id == "github:org/repo"
        assert fs.error_type == "ConnectorTimeoutError"
        assert "8.0" in fs.message

    @pytest.mark.asyncio
    async def test_elapsed_within_budget(self) -> None:
        """Four connectors (one timing out at 3 s) complete within 3 s + 200 ms."""
        connectors = {
            "echo:c1": _fast_connector("echo:c1"),
            "echo:c2": _fast_connector("echo:c2"),
            "echo:c3": _fast_connector("echo:c3"),
            "grafana:dash": _slow_connector(delay=10.0),
        }
        registry = _make_registry(connectors)
        dispatcher = ParallelConnectorDispatcher(connector_registry=registry)

        t0 = time.monotonic()
        result = await dispatcher.fetch_all(
            query="test",
            source_ids=list(connectors.keys()),
            token_budget_per_source={},
        )
        elapsed = time.monotonic() - t0

        assert len(result.chunks) == 3
        assert len(result.failed_sources) == 1
        # grafana uses 3 s override; add 200 ms buffer for CI overhead
        assert elapsed < 3.2, f"elapsed {elapsed:.2f}s exceeds 3 s timeout + 200 ms buffer"


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    @pytest.mark.asyncio
    async def test_timeout_counter_increments(self) -> None:
        from src.agents.retrieval.metrics import connector_failure_count

        slow = _slow_connector(delay=10.0)
        dispatcher = ParallelConnectorDispatcher(connector_registry=MagicMock())

        before = _read_counter(connector_failure_count, {"connector_id": "grafana:m", "failure_type": "timeout"})

        with pytest.raises(ConnectorTimeoutError):
            await dispatcher._fetch_one(
                source_id="grafana:m",
                connector=slow,
                query="cpu",
                token_budget=None,
            )

        after = _read_counter(connector_failure_count, {"connector_id": "grafana:m", "failure_type": "timeout"})
        assert after - before == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_error_counter_increments(self) -> None:
        from src.agents.retrieval.metrics import connector_failure_count

        exc = RuntimeError("boom")
        bad = _error_connector(exc)
        dispatcher = ParallelConnectorDispatcher(connector_registry=MagicMock())

        before = _read_counter(
            connector_failure_count,
            {"connector_id": "echo:bad", "failure_type": "error"},
        )

        with pytest.raises(RuntimeError):
            await dispatcher._fetch_one(
                source_id="echo:bad",
                connector=bad,
                query="test",
                token_budget=None,
            )

        after = _read_counter(
            connector_failure_count,
            {"connector_id": "echo:bad", "failure_type": "error"},
        )
        assert after - before == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_duration_observed_on_success(self) -> None:
        from src.agents.retrieval.metrics import connector_fetch_duration

        fast = _fast_connector("echo:ok")
        dispatcher = ParallelConnectorDispatcher(connector_registry=MagicMock())

        before = _read_histogram_count(
            connector_fetch_duration, {"connector_id": "echo:ok", "status": "success"}
        )

        await dispatcher._fetch_one(
            source_id="echo:ok",
            connector=fast,
            query="test",
            token_budget=None,
        )

        after = _read_histogram_count(
            connector_fetch_duration, {"connector_id": "echo:ok", "status": "success"}
        )
        assert after - before == 1


# ---------------------------------------------------------------------------
# Metric reading helpers
# ---------------------------------------------------------------------------


def _read_counter(metric: object, labels: dict) -> float:
    """Read the current value of a prometheus_client Counter sample."""
    from prometheus_client import REGISTRY

    name = metric._name  # type: ignore[attr-defined]
    return REGISTRY.get_sample_value(name + "_total", labels) or 0.0


def _read_histogram_count(metric: object, labels: dict) -> float:
    """Read the _count sample of a prometheus_client Histogram."""
    from prometheus_client import REGISTRY

    name = metric._name  # type: ignore[attr-defined]
    return REGISTRY.get_sample_value(name + "_count", labels) or 0.0
