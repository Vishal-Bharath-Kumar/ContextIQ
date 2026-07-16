"""Unit tests for CronSyncScheduler._is_due() — TASK-US026-05.

Pure unit tests with no DB, Kafka, or external I/O.
Validates the cron due-time logic in isolation.

Acceptance criteria verified:
  AC-1  _is_due() returns True when last_sync_at is None (first-ever sync)
  AC-2  _is_due() returns True when the next scheduled run time has passed
  AC-3  _is_due() returns False when the next scheduled run time is in the future
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.knowledge_sources.sync.scheduler import CronSyncScheduler


def _scheduler() -> CronSyncScheduler:
    """Construct a CronSyncScheduler with no real I/O dependencies."""
    return CronSyncScheduler(session_factory=None, registry=None)  # type: ignore[arg-type]


def test_is_due_when_no_prior_sync() -> None:
    """A source that has never synced is always due."""
    assert _scheduler()._is_due("0 */6 * * *", None, datetime.now(tz=UTC))


def test_is_due_when_next_run_is_past() -> None:
    """Next cron fire time is in the past — source is due."""
    last = datetime.now(tz=UTC) - timedelta(hours=7)
    assert _scheduler()._is_due("0 */6 * * *", last, datetime.now(tz=UTC))


def test_not_due_when_next_run_is_future() -> None:
    """Next cron fire time is in the future — source is not yet due."""
    last = datetime.now(tz=UTC) - timedelta(hours=1)
    assert not _scheduler()._is_due("0 */6 * * *", last, datetime.now(tz=UTC))
