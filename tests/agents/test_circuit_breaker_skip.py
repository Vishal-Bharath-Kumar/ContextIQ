"""Unit tests for pre-dispatch circuit-breaker skip — TASK-US008-02.

Acceptance criteria verified:
  - open_circuit_not_dispatched:       open-circuit connector not included in asyncio.gather
    task list (verified via task-count assertion)
  - open_circuit_in_failed_sources:    open-circuit connector appears in failed_sources with
    error_type == "ConnectorCircuitOpenError"
  - all_circuits_open_empty_chunks:    when all connectors have open circuits, chunks is empty
    and failed_sources contains all skipped connectors
  - skip_counter_increments:           connector_failure_count{failure_type="circuit_open"} increments
    for each skipped connector
  - half_open_dispatched_normally:     half-open connector (is_open() == False) included in
    dispatch as a normal call
  - mixed_open_closed_task_count:      1 open + 2 closed connectors → gather called with 2 tasks;
    open connector in failed_sources
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.retrieval.connector_circuit_breaker import ConnectorCircuitBreakerRegistry
from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FETCHED_AT = datetime(2026, 7, 16, tzinfo=UTC)

_SOURCE_OPEN = "github:open-circuit"
_SOURCE_CLOSED_A = "jira:closed-a"
_SOURCE_CLOSED_B = "confluence:closed-b"


def _make_result(source_id: str = "item-1", content: str = "hello") -> ConnectorResult:
    return ConnectorResult(
        source_id=source_id,
        content=content,
        metadata=ResultMetadata(source_url="https://example.com"),
        fetched_at=_FETCHED_AT,
    )


def _fast_connector(source_id: str) -> MagicMock:
    connector = MagicMock()
    connector.fetch = AsyncMock(return_value=[_make_result(source_id)])
    return connector


def _make_connector_registry(source_map: dict) -> MagicMock:
    registry = MagicMock()
    registry.get.side_effect = lambda src: source_map.get(src)
    return registry


def _make_breaker_registry(open_ids: set[str]) -> MagicMock:
    breaker_registry = MagicMock(spec=ConnectorCircuitBreakerRegistry)
    breaker_registry.is_open.side_effect = lambda src: src in open_ids
    return breaker_registry


def _make_dispatcher(
    source_map: dict,
    open_ids: set[str],
    timeout_seconds: float = 1.0,
) -> ParallelConnectorDispatcher:
    connector_registry = _make_connector_registry(source_map)
    breaker_registry = _make_breaker_registry(open_ids)
    dispatcher = ParallelConnectorDispatcher(
        connector_registry=connector_registry,
        timeout_seconds=timeout_seconds,
        breaker_registry=breaker_registry,
    )
    return dispatcher


# ---------------------------------------------------------------------------
# open_circuit_not_dispatched
# ---------------------------------------------------------------------------


class TestOpenCircuitNotDispatched:
    @pytest.mark.asyncio
    async def test_open_circuit_not_dispatched(self) -> None:
        """An open-circuit connector must not be included in asyncio.gather tasks."""
        open_connector = _fast_connector(_SOURCE_OPEN)
        closed_connector = _fast_connector(_SOURCE_CLOSED_A)

        source_map = {
            _SOURCE_OPEN: open_connector,
            _SOURCE_CLOSED_A: closed_connector,
        }
        dispatcher = _make_dispatcher(source_map, open_ids={_SOURCE_OPEN})

        gathered_tasks: list = []

        original_gather = asyncio.gather

        async def _spy_gather(*tasks: object, **kwargs: object) -> list:
            gathered_tasks.extend(tasks)
            return await original_gather(*tasks, **kwargs)  # type: ignore[arg-type]

        with patch("src.agents.retrieval.parallel_dispatcher.asyncio.gather", side_effect=_spy_gather):
            result = await dispatcher.fetch_all(
                query="test",
                source_ids=[_SOURCE_OPEN, _SOURCE_CLOSED_A],
                token_budget_per_source={},
            )

        # Only 1 task for the closed connector
        assert len(gathered_tasks) == 1
        open_connector.fetch.assert_not_called()
        assert len(result.chunks) == 1
        assert result.chunks[0].source_id == _SOURCE_CLOSED_A


# ---------------------------------------------------------------------------
# open_circuit_in_failed_sources
# ---------------------------------------------------------------------------


class TestOpenCircuitInFailedSources:
    @pytest.mark.asyncio
    async def test_open_circuit_appears_in_failed_sources(self) -> None:
        source_map = {_SOURCE_OPEN: _fast_connector(_SOURCE_OPEN)}
        dispatcher = _make_dispatcher(source_map, open_ids={_SOURCE_OPEN})

        result = await dispatcher.fetch_all(
            query="test",
            source_ids=[_SOURCE_OPEN],
            token_budget_per_source={},
        )

        assert len(result.failed_sources) == 1
        failed = result.failed_sources[0]
        assert failed.source_id == _SOURCE_OPEN
        assert failed.error_type == "ConnectorCircuitOpenError"
        assert "Circuit breaker open" in failed.message

    @pytest.mark.asyncio
    async def test_open_circuit_message_contains_source_id(self) -> None:
        source_map = {_SOURCE_OPEN: _fast_connector(_SOURCE_OPEN)}
        dispatcher = _make_dispatcher(source_map, open_ids={_SOURCE_OPEN})

        result = await dispatcher.fetch_all(
            query="test",
            source_ids=[_SOURCE_OPEN],
            token_budget_per_source={},
        )

        assert _SOURCE_OPEN in result.failed_sources[0].message


# ---------------------------------------------------------------------------
# all_circuits_open_empty_chunks
# ---------------------------------------------------------------------------


class TestAllCircuitsOpen:
    @pytest.mark.asyncio
    async def test_all_circuits_open_returns_empty_chunks(self) -> None:
        source_map = {
            _SOURCE_OPEN: _fast_connector(_SOURCE_OPEN),
            _SOURCE_CLOSED_A: _fast_connector(_SOURCE_CLOSED_A),
        }
        dispatcher = _make_dispatcher(
            source_map, open_ids={_SOURCE_OPEN, _SOURCE_CLOSED_A}
        )

        result = await dispatcher.fetch_all(
            query="test",
            source_ids=[_SOURCE_OPEN, _SOURCE_CLOSED_A],
            token_budget_per_source={},
        )

        assert result.chunks == []
        assert len(result.failed_sources) == 2
        failed_ids = {f.source_id for f in result.failed_sources}
        assert failed_ids == {_SOURCE_OPEN, _SOURCE_CLOSED_A}
        for failed in result.failed_sources:
            assert failed.error_type == "ConnectorCircuitOpenError"

    @pytest.mark.asyncio
    async def test_all_circuits_open_no_network_calls(self) -> None:
        open_connector_a = _fast_connector(_SOURCE_OPEN)
        open_connector_b = _fast_connector(_SOURCE_CLOSED_A)

        source_map = {
            _SOURCE_OPEN: open_connector_a,
            _SOURCE_CLOSED_A: open_connector_b,
        }
        dispatcher = _make_dispatcher(
            source_map, open_ids={_SOURCE_OPEN, _SOURCE_CLOSED_A}
        )

        await dispatcher.fetch_all(
            query="test",
            source_ids=[_SOURCE_OPEN, _SOURCE_CLOSED_A],
            token_budget_per_source={},
        )

        open_connector_a.fetch.assert_not_called()
        open_connector_b.fetch.assert_not_called()


# ---------------------------------------------------------------------------
# skip_counter_increments
# ---------------------------------------------------------------------------


class TestSkipCounterIncrements:
    @pytest.mark.asyncio
    async def test_skip_counter_increments_for_each_open_circuit(self) -> None:
        source_map = {
            _SOURCE_OPEN: _fast_connector(_SOURCE_OPEN),
            _SOURCE_CLOSED_A: _fast_connector(_SOURCE_CLOSED_A),
            _SOURCE_CLOSED_B: _fast_connector(_SOURCE_CLOSED_B),
        }
        dispatcher = _make_dispatcher(
            source_map, open_ids={_SOURCE_OPEN, _SOURCE_CLOSED_A}
        )

        increment_calls: list[str] = []

        import src.agents.retrieval.metrics as metrics_module

        class _LabelsSpy:
            def __init__(self, connector_id: str, failure_type: str) -> None:
                self._connector_id = connector_id

            def inc(self) -> None:
                increment_calls.append(self._connector_id)

        mock_counter = MagicMock()
        mock_counter.labels.side_effect = lambda connector_id, failure_type: _LabelsSpy(connector_id, failure_type)

        with patch.object(metrics_module, "connector_failure_count", mock_counter):
            with patch(
                "src.agents.retrieval.parallel_dispatcher.connector_failure_count",
                mock_counter,
            ):
                await dispatcher.fetch_all(
                    query="test",
                    source_ids=[_SOURCE_OPEN, _SOURCE_CLOSED_A, _SOURCE_CLOSED_B],
                    token_budget_per_source={},
                )

        assert sorted(increment_calls) == sorted([_SOURCE_OPEN, _SOURCE_CLOSED_A])

    @pytest.mark.asyncio
    async def test_skip_counter_not_incremented_for_closed_circuit(self) -> None:
        source_map = {_SOURCE_CLOSED_A: _fast_connector(_SOURCE_CLOSED_A)}
        dispatcher = _make_dispatcher(source_map, open_ids=set())

        import src.agents.retrieval.parallel_dispatcher as dispatcher_module

        mock_counter = MagicMock()

        with patch.object(dispatcher_module, "connector_failure_count", mock_counter):
            await dispatcher.fetch_all(
                query="test",
                source_ids=[_SOURCE_CLOSED_A],
                token_budget_per_source={},
            )

        mock_counter.labels.assert_not_called()


# ---------------------------------------------------------------------------
# half_open_dispatched_normally
# ---------------------------------------------------------------------------


class TestHalfOpenDispatchedNormally:
    @pytest.mark.asyncio
    async def test_half_open_connector_is_dispatched(self) -> None:
        """Half-open connector (is_open() == False) must be dispatched normally."""
        _SOURCE_HALF_OPEN = "jira:half-open"
        half_open_connector = _fast_connector(_SOURCE_HALF_OPEN)

        source_map = {_SOURCE_HALF_OPEN: half_open_connector}
        # is_open() returns False for half-open — only truly open returns True
        dispatcher = _make_dispatcher(source_map, open_ids=set())

        result = await dispatcher.fetch_all(
            query="test",
            source_ids=[_SOURCE_HALF_OPEN],
            token_budget_per_source={},
        )

        half_open_connector.fetch.assert_called_once()
        assert result.failed_sources == []
        assert len(result.chunks) == 1
        assert result.chunks[0].source_id == _SOURCE_HALF_OPEN


# ---------------------------------------------------------------------------
# mixed_open_closed_task_count
# ---------------------------------------------------------------------------


class TestMixedOpenClosedTaskCount:
    @pytest.mark.asyncio
    async def test_one_open_two_closed_gather_receives_two_tasks(self) -> None:
        """1 open + 2 closed connectors → gather called with exactly 2 tasks."""
        source_map = {
            _SOURCE_OPEN: _fast_connector(_SOURCE_OPEN),
            _SOURCE_CLOSED_A: _fast_connector(_SOURCE_CLOSED_A),
            _SOURCE_CLOSED_B: _fast_connector(_SOURCE_CLOSED_B),
        }
        dispatcher = _make_dispatcher(source_map, open_ids={_SOURCE_OPEN})

        gathered_tasks: list = []
        original_gather = asyncio.gather

        async def _spy_gather(*tasks: object, **kwargs: object) -> list:
            gathered_tasks.extend(tasks)
            return await original_gather(*tasks, **kwargs)  # type: ignore[arg-type]

        with patch("src.agents.retrieval.parallel_dispatcher.asyncio.gather", side_effect=_spy_gather):
            result = await dispatcher.fetch_all(
                query="test",
                source_ids=[_SOURCE_OPEN, _SOURCE_CLOSED_A, _SOURCE_CLOSED_B],
                token_budget_per_source={},
            )

        # Exactly 2 tasks dispatched — the open connector was excluded
        assert len(gathered_tasks) == 2

        # Open connector is in failed_sources
        failed_ids = {f.source_id for f in result.failed_sources}
        assert _SOURCE_OPEN in failed_ids
        assert all(
            f.error_type == "ConnectorCircuitOpenError"
            for f in result.failed_sources
            if f.source_id == _SOURCE_OPEN
        )

        # Closed connectors returned chunks
        chunk_source_ids = {c.source_id for c in result.chunks}
        assert _SOURCE_CLOSED_A in chunk_source_ids
        assert _SOURCE_CLOSED_B in chunk_source_ids

    @pytest.mark.asyncio
    async def test_runtime_failures_combined_with_pre_failed(self) -> None:
        """Runtime failure from a closed connector is combined with pre-failed open circuits."""
        _SOURCE_RUNTIME_ERR = "slack:runtime-error"

        async def _error_fetch(_query: object) -> list:
            raise RuntimeError("downstream error")

        error_connector = MagicMock()
        error_connector.fetch = AsyncMock(side_effect=_error_fetch)

        source_map = {
            _SOURCE_OPEN: _fast_connector(_SOURCE_OPEN),
            _SOURCE_RUNTIME_ERR: error_connector,
            _SOURCE_CLOSED_B: _fast_connector(_SOURCE_CLOSED_B),
        }
        dispatcher = _make_dispatcher(source_map, open_ids={_SOURCE_OPEN})

        result = await dispatcher.fetch_all(
            query="test",
            source_ids=[_SOURCE_OPEN, _SOURCE_RUNTIME_ERR, _SOURCE_CLOSED_B],
            token_budget_per_source={},
        )

        failed_ids = {f.source_id for f in result.failed_sources}
        assert _SOURCE_OPEN in failed_ids
        assert _SOURCE_RUNTIME_ERR in failed_ids
        assert len(result.chunks) == 1
        assert result.chunks[0].source_id == _SOURCE_CLOSED_B

        # Verify error types
        error_by_source = {f.source_id: f.error_type for f in result.failed_sources}
        assert error_by_source[_SOURCE_OPEN] == "ConnectorCircuitOpenError"
        assert error_by_source[_SOURCE_RUNTIME_ERR] == "RuntimeError"
