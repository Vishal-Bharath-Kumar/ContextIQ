"""CronSyncScheduler — cron-driven background sync task — TASK-US026-03.

Ticks every minute (configurable), reads all active knowledge sources from
PostgreSQL, evaluates each source's `sync_schedule` cron expression using
`croniter`, and dispatches a `SyncJobExecutor.run()` call for every source
whose next scheduled time has passed.

Satisfies US-026 AC-1 and AC-2.  Starts via FastAPI lifespan and cancels
cleanly on shutdown.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from croniter import croniter
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.connector_sdk.registry import ConnectorRegistry
from src.knowledge_sources.repositories.knowledge_source_repository import (
    KnowledgeSourceRepository,
)
from src.knowledge_sources.sync.executor import SyncExecutorSettings, SyncJobExecutor

_log = logging.getLogger(__name__)


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYNC_SCHEDULER_", env_file=".env", extra="ignore"
    )

    tick_interval_s: int = 60  # how often the scheduler wakes to evaluate due sources
    lookahead_s: int = 60  # sources due within the next N seconds are considered due now


class CronSyncScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ConnectorRegistry,
        settings: SchedulerSettings | None = None,
        executor_settings: SyncExecutorSettings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._settings = settings or SchedulerSettings()
        self._executor_settings = executor_settings or SyncExecutorSettings()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the background scheduling loop. Idempotent."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="cron_sync_scheduler")

    def stop(self) -> None:
        """Cancel the scheduling task. Called from lifespan teardown."""
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as exc:
                _log.error("scheduler_tick_failed", extra={"error": str(exc)})
            await asyncio.sleep(self._settings.tick_interval_s)

    async def _tick(self) -> None:
        """Evaluate all active sources; dispatch sync for those whose cron time has passed."""
        now = datetime.now(tz=UTC)
        async with self._session_factory() as session:
            repo = KnowledgeSourceRepository(session)
            sources = await repo.list_active()  # returns only is_active=True records

        for source in sources:
            try:
                due = self._is_due(source.sync_schedule, source.last_sync_at, now)
            except Exception as exc:
                _log.warning(
                    "invalid_cron_expression",
                    extra={
                        "source_id": str(source.id),
                        "schedule": source.sync_schedule,
                        "error": str(exc),
                    },
                )
                continue

            if due:
                _log.info(
                    "dispatching_sync",
                    extra={
                        "source_id": str(source.id),
                        "connector_type": source.connector_type,
                        "schedule": source.sync_schedule,
                    },
                )
                # Fire-and-forget: sync runs in a separate task so the tick is non-blocking
                asyncio.create_task(
                    self._run_sync(source.id),
                    name=f"sync_{source.id}",
                )

    def _is_due(
        self,
        cron_expr: str,
        last_sync_at: datetime | None,
        now: datetime,
    ) -> bool:
        """Return True if the cron expression is due at ``now``.

        A source with no prior sync is always considered due.
        Uses croniter to find the next scheduled time after last_sync_at.
        """
        if last_sync_at is None:
            return True
        cron = croniter(cron_expr, last_sync_at)
        next_run: datetime = cron.get_next(datetime)
        return next_run <= now

    async def _run_sync(self, source_id: UUID) -> None:
        async with self._session_factory() as session:
            executor = SyncJobExecutor(
                session=session,
                registry=self._registry,
                settings=self._executor_settings,
            )
            try:
                await executor.run(source_id)
            except Exception as exc:
                _log.error(
                    "scheduled_sync_failed",
                    extra={"source_id": str(source_id), "error": str(exc)},
                )
