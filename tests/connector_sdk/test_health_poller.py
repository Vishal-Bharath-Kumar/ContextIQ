"""
Unit tests for TASK-US021-03: ConnectorHealthPoller — 30-Second Background Health Check.

Coverage targets (all acceptance criteria):
  - _poll_once() calls health_check() on all records in the registry
  - After _poll_once() with an unhealthy connector, registry.get() returns None
  - connector_health_checks_total increments with status="unhealthy" on failure
  - connector_health_checks_total increments with status="healthy" on success
  - connectors_enabled_gauge reflects the correct enabled count after each poll
  - health_check() raising an exception is caught; connector marked unhealthy; no propagation
  - poller.stop() cancels the background task without CancelledError propagation
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connector_sdk.health_poller import ConnectorHealthPoller
from src.connector_sdk.registry import ConnectorRecord, ConnectorRegistry
from src.connector_sdk.schemas.health import HealthStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _make_record(
    connector_id: str,
    *,
    healthy: bool = True,
    raises: bool = False,
) -> ConnectorRecord:
    """Return a ConnectorRecord whose health_check() is an AsyncMock."""
    instance = MagicMock()
    if raises:
        instance.health_check = AsyncMock(side_effect=RuntimeError("boom"))
    else:
        instance.health_check = AsyncMock(
            return_value=HealthStatus(
                healthy=healthy,
                message="ok" if healthy else "down",
                checked_at=_utc_now(),
            )
        )
    record = MagicMock(spec=ConnectorRecord)
    record.connector_id = connector_id
    record.instance = instance
    return record


def _make_registry(records: list[ConnectorRecord]) -> ConnectorRegistry:
    """Return a ConnectorRegistry whose records() / all_enabled() are stubbed."""
    registry = MagicMock(spec=ConnectorRegistry)
    registry.records.return_value = records
    registry.all_enabled.return_value = [r for r in records if not hasattr(r, "_disabled")]
    return registry


# ---------------------------------------------------------------------------
# _poll_once — happy path (all healthy)
# ---------------------------------------------------------------------------

class TestPollOnceHealthy:
    @pytest.mark.asyncio
    async def test_health_check_called_for_each_record(self) -> None:
        rec_a = _make_record("a", healthy=True)
        rec_b = _make_record("b", healthy=True)
        registry = _make_registry([rec_a, rec_b])
        registry.all_enabled.return_value = [rec_a.instance, rec_b.instance]

        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_labels = MagicMock()
            mock_ctr.labels.return_value = mock_labels
            await poller._poll_once()

        rec_a.instance.health_check.assert_awaited_once()
        rec_b.instance.health_check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_counter_incremented_healthy(self) -> None:
        rec = _make_record("c", healthy=True)
        registry = _make_registry([rec])
        registry.all_enabled.return_value = [rec.instance]
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_labels = MagicMock()
            mock_ctr.labels.return_value = mock_labels
            await poller._poll_once()

        mock_ctr.labels.assert_called_once_with(connector_id="c", status="healthy")
        mock_labels.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_health_called_healthy(self) -> None:
        rec = _make_record("d", healthy=True)
        registry = _make_registry([rec])
        registry.all_enabled.return_value = [rec.instance]
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_ctr.labels.return_value = MagicMock()
            await poller._poll_once()

        registry.set_health.assert_called_once()
        call_kwargs = registry.set_health.call_args.kwargs
        assert call_kwargs["connector_id"] == "d"
        assert call_kwargs["healthy"] is True

    @pytest.mark.asyncio
    async def test_gauge_set_after_poll(self) -> None:
        rec_a = _make_record("e", healthy=True)
        rec_b = _make_record("f", healthy=True)
        registry = _make_registry([rec_a, rec_b])
        registry.all_enabled.return_value = [rec_a.instance, rec_b.instance]
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge") as mock_gauge:
            mock_ctr.labels.return_value = MagicMock()
            await poller._poll_once()

        mock_gauge.set.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# _poll_once — unhealthy connector
# ---------------------------------------------------------------------------

class TestPollOnceUnhealthy:
    @pytest.mark.asyncio
    async def test_counter_incremented_unhealthy(self) -> None:
        rec = _make_record("g", healthy=False)
        registry = _make_registry([rec])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_labels = MagicMock()
            mock_ctr.labels.return_value = mock_labels
            await poller._poll_once()

        mock_ctr.labels.assert_called_once_with(connector_id="g", status="unhealthy")
        mock_labels.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_health_called_unhealthy(self) -> None:
        rec = _make_record("h", healthy=False)
        registry = _make_registry([rec])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_ctr.labels.return_value = MagicMock()
            await poller._poll_once()

        call_kwargs = registry.set_health.call_args.kwargs
        assert call_kwargs["connector_id"] == "h"
        assert call_kwargs["healthy"] is False

    @pytest.mark.asyncio
    async def test_registry_get_returns_none_after_unhealthy(self) -> None:
        """Integration-style test using a real registry."""
        from src.connector_sdk.base import BaseConnector
        from src.connector_sdk.schemas.query import ConnectorQuery
        from src.connector_sdk.schemas.result import ConnectorResult
        from src.connector_sdk.schemas.sync import SyncResult

        class _UnhealthyConnector(BaseConnector):
            async def authenticate(self) -> None:
                pass

            async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
                return []

            async def sync(self) -> SyncResult:
                return SyncResult(items_processed=0, items_failed=0, last_sync_at=_utc_now())

            async def health_check(self) -> HealthStatus:
                return HealthStatus(healthy=False, message="down", checked_at=_utc_now())

        real_registry = ConnectorRegistry()
        await real_registry.load(connector_classes={"unhealthy_conn": _UnhealthyConnector})
        # Confirm it was enabled before poll
        assert real_registry.get("unhealthy_conn") is not None

        poller = ConnectorHealthPoller(registry=real_registry, interval_s=0)
        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_ctr.labels.return_value = MagicMock()
            await poller._poll_once()

        assert real_registry.get("unhealthy_conn") is None


# ---------------------------------------------------------------------------
# _poll_once — health_check() raises
# ---------------------------------------------------------------------------

class TestPollOnceRaises:
    @pytest.mark.asyncio
    async def test_exception_caught_connector_marked_unhealthy(self) -> None:
        rec = _make_record("i", raises=True)
        registry = _make_registry([rec])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_labels = MagicMock()
            mock_ctr.labels.return_value = mock_labels
            # Must not raise
            await poller._poll_once()

        mock_ctr.labels.assert_called_once_with(connector_id="i", status="unhealthy")
        mock_labels.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self) -> None:
        rec = _make_record("j", raises=True)
        registry = _make_registry([rec])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total") as mock_ctr, \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            mock_ctr.labels.return_value = MagicMock()
            try:
                await poller._poll_once()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"_poll_once() propagated an exception: {exc}")


# ---------------------------------------------------------------------------
# start() / stop() lifecycle
# ---------------------------------------------------------------------------

class TestPollerLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_task(self) -> None:
        registry = _make_registry([])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=9999)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total"), \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            poller.start()
            assert poller._task is not None
            assert not poller._task.done()
            poller.stop()
            await asyncio.sleep(0)  # allow cancellation to propagate

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        registry = _make_registry([])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=9999)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total"), \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            poller.start()
            first_task = poller._task
            poller.start()  # second call — should not replace running task
            assert poller._task is first_task
            poller.stop()
            await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self) -> None:
        registry = _make_registry([])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=9999)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total"), \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            poller.start()
            task = poller._task
            poller.stop()
            await asyncio.sleep(0)  # yield so asyncio processes cancellation

        assert task is not None
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_stop_does_not_raise_cancelled_error(self) -> None:
        """CancelledError must not propagate to the caller of stop()."""
        registry = _make_registry([])
        registry.all_enabled.return_value = []
        poller = ConnectorHealthPoller(registry=registry, interval_s=9999)

        with patch("src.connector_sdk.health_poller.connector_health_checks_total"), \
             patch("src.connector_sdk.health_poller.connectors_enabled_gauge"):
            poller.start()
            try:
                poller.stop()
            except asyncio.CancelledError:
                pytest.fail("stop() propagated CancelledError")
            await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_stop_noop_when_not_started(self) -> None:
        registry = _make_registry([])
        poller = ConnectorHealthPoller(registry=registry, interval_s=0)
        # Must not raise
        poller.stop()
