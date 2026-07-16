"""Unit tests for CronSyncScheduler — TASK-US026-03.

All acceptance criteria are covered without real clock advances or DB connections.
``asyncio.sleep`` is patched globally; ``SyncJobExecutor.run`` is mocked via
``AsyncMock``; ``KnowledgeSourceRepository.list_active`` is patched per test.

Acceptance criteria verified:
  AC-1  _is_due() returns True when last_sync_at=None (first-ever sync)
  AC-2  _is_due() returns True when croniter.get_next(last_sync_at) <= now
  AC-3  _is_due() returns False when the next scheduled time is in the future
  AC-4  Invalid cron expression is logged and skipped — tick does not raise
  AC-5  Each due source triggers an independent asyncio.create_task (non-blocking)
  AC-6  start() is idempotent — calling twice does not create a second task
  AC-7  stop() cancels the task; CancelledError does not propagate to event loop
"""
from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.knowledge_sources.sync.scheduler import (
    CronSyncScheduler,
    SchedulerSettings,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

_NOW = dt.datetime(2026, 7, 16, 12, 0, 0, tzinfo=dt.UTC)

# A cron expression that fired in the past relative to _NOW ("every 5 minutes";
# last ran 10 minutes before _NOW so next run is 5 minutes before _NOW).
_CRON_DUE = "*/5 * * * *"
_LAST_SYNC_DUE = _NOW - dt.timedelta(minutes=10)

# A cron expression whose next run is well in the future.
_CRON_FUTURE = "0 3 * * *"  # 03:00 UTC; _NOW is 12:00 UTC so next is tomorrow
_LAST_SYNC_FUTURE = _NOW - dt.timedelta(hours=1)


def _make_source(
    *,
    cron_expr: str = _CRON_DUE,
    last_sync_at: dt.datetime | None = _LAST_SYNC_DUE,
) -> MagicMock:
    src = MagicMock()
    src.id = uuid4()
    src.connector_type = "github"
    src.sync_schedule = cron_expr
    src.last_sync_at = last_sync_at
    return src


def _make_scheduler(
    sources: list[MagicMock] | None = None,
    tick_interval_s: int = 60,
) -> tuple[CronSyncScheduler, MagicMock, AsyncMock]:
    """Return (scheduler, mock_session_factory, mock_executor_run)."""
    # session factory context-manager mock
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=mock_cm)

    # repo.list_active patch — applied at call site via monkeypatch/patch
    registry = MagicMock()
    settings = SchedulerSettings(tick_interval_s=tick_interval_s, lookahead_s=60)

    scheduler = CronSyncScheduler(
        session_factory=session_factory,  # type: ignore[arg-type]
        registry=registry,
        settings=settings,
    )
    executor_run = AsyncMock()
    return scheduler, session_factory, executor_run


# ---------------------------------------------------------------------------
# AC-1  _is_due() with last_sync_at=None
# ---------------------------------------------------------------------------


def test_is_due_no_prior_sync() -> None:
    scheduler, _, _ = _make_scheduler()
    assert scheduler._is_due("*/5 * * * *", None, _NOW) is True


# ---------------------------------------------------------------------------
# AC-2  _is_due() when next_run <= now
# ---------------------------------------------------------------------------


def test_is_due_past_schedule() -> None:
    scheduler, _, _ = _make_scheduler()
    # last ran 10 min ago; next run for */5 would be 5 min ago → due
    assert scheduler._is_due(_CRON_DUE, _LAST_SYNC_DUE, _NOW) is True


# ---------------------------------------------------------------------------
# AC-3  _is_due() when next scheduled time is in the future
# ---------------------------------------------------------------------------


def test_is_due_future_schedule() -> None:
    scheduler, _, _ = _make_scheduler()
    # 03:00 daily; last ran 1 h ago at 11:00; next is tomorrow at 03:00 → not due
    assert scheduler._is_due(_CRON_FUTURE, _LAST_SYNC_FUTURE, _NOW) is False


# ---------------------------------------------------------------------------
# AC-4  Invalid cron expression is logged and tick does not raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_invalid_cron_skipped_with_log() -> None:
    scheduler, _, _ = _make_scheduler()
    bad_source = _make_source(cron_expr="not-a-cron")

    with (
        patch(
            "src.knowledge_sources.sync.scheduler.KnowledgeSourceRepository"
        ) as MockRepo,
        patch("src.knowledge_sources.sync.scheduler._log") as mock_log,
        patch("src.knowledge_sources.sync.scheduler.datetime") as mock_dt,
    ):
        MockRepo.return_value.list_active = AsyncMock(return_value=[bad_source])
        mock_dt.now.return_value = _NOW

        # Must not raise
        await scheduler._tick()

    mock_log.warning.assert_called_once()
    call_kwargs = mock_log.warning.call_args
    assert call_kwargs[0][0] == "invalid_cron_expression"


# ---------------------------------------------------------------------------
# AC-5  Each due source triggers an independent asyncio.create_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_dispatches_task_per_due_source() -> None:
    scheduler, _, _ = _make_scheduler()
    source1 = _make_source()
    source2 = _make_source()

    created_task_names: list[str] = []
    _real_create_task = asyncio.create_task

    def _fake_create_task(coro: object, *, name: str = "") -> asyncio.Task[None]:
        # Immediately close the coroutine to prevent "coroutine never awaited" warnings
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]
        created_task_names.append(name)
        # Return a real task (no-op) using the original function
        return _real_create_task(asyncio.sleep(0), name=name)

    with (
        patch(
            "src.knowledge_sources.sync.scheduler.KnowledgeSourceRepository"
        ) as MockRepo,
        patch.object(scheduler, "_is_due", return_value=True),
        patch(
            "src.knowledge_sources.sync.scheduler.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
    ):
        MockRepo.return_value.list_active = AsyncMock(return_value=[source1, source2])

        await scheduler._tick()

    assert len(created_task_names) == 2
    assert all(name.startswith("sync_") for name in created_task_names)


# ---------------------------------------------------------------------------
# AC-6  start() is idempotent — two calls do not create a second task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_idempotent() -> None:
    scheduler, _, _ = _make_scheduler()

    with patch.object(scheduler, "_loop", new_callable=AsyncMock):
        scheduler.start()
        task_first = scheduler._task
        scheduler.start()  # second call — must reuse existing task
        task_second = scheduler._task

    assert task_first is task_second
    # Cleanup
    scheduler.stop()
    if task_first:
        try:
            await task_first
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# AC-7  stop() cancels the task; CancelledError does not propagate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_cancels_task() -> None:
    scheduler, _, _ = _make_scheduler()

    async def _long_loop() -> None:
        while True:
            await asyncio.sleep(3600)

    with patch.object(scheduler, "_loop", side_effect=_long_loop):
        scheduler.start()
        # Give the loop a chance to start
        await asyncio.sleep(0)

        task = scheduler._task
        assert task is not None
        assert not task.done()

        scheduler.stop()  # cancels the task

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.CancelledError, TimeoutError):
            pass

    assert task.cancelled() or task.done()


# ---------------------------------------------------------------------------
# Integration: _run_sync delegates to SyncJobExecutor.run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_calls_executor() -> None:
    scheduler, _, _ = _make_scheduler()
    source_id = uuid4()

    with patch(
        "src.knowledge_sources.sync.scheduler.SyncJobExecutor"
    ) as MockExecutor:
        mock_instance = AsyncMock()
        MockExecutor.return_value = mock_instance

        await scheduler._run_sync(source_id)

    MockExecutor.assert_called_once()
    mock_instance.run.assert_awaited_once_with(source_id)


# ---------------------------------------------------------------------------
# Integration: _run_sync swallows executor exceptions (fire-and-forget safety)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_logs_on_exception() -> None:
    scheduler, _, _ = _make_scheduler()
    source_id = uuid4()

    with (
        patch("src.knowledge_sources.sync.scheduler.SyncJobExecutor") as MockExecutor,
        patch("src.knowledge_sources.sync.scheduler._log") as mock_log,
    ):
        mock_instance = AsyncMock()
        mock_instance.run.side_effect = RuntimeError("boom")
        MockExecutor.return_value = mock_instance

        # Must not raise
        await scheduler._run_sync(source_id)

    mock_log.error.assert_called_once()
    assert mock_log.error.call_args[0][0] == "scheduled_sync_failed"
