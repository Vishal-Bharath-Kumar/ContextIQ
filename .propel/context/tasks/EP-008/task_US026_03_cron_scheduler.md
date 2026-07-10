# TASK-US026-03 — `CronSyncScheduler`: Cron-Driven Background Sync Task

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US026-03 |
| User Story | US-026 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `CronSyncScheduler` — a background `asyncio.Task` that ticks every minute, reads all active knowledge sources from PostgreSQL, evaluates each source's `sync_schedule` cron expression using `croniter`, and dispatches a `SyncJobExecutor.run()` call for every source whose next scheduled time has passed. Satisfies US-026 AC-1 and AC-2. Starts in the FastAPI lifespan and cancels cleanly on shutdown.

## Implementation Details

**Technology:** Python 3.11+, `croniter>=1.4`, `asyncio`, SQLAlchemy 2.x async

**File locations:**
- `src/knowledge_sources/sync/scheduler.py` — `CronSyncScheduler`, `SchedulerSettings`
- `src/agents/worker/lifespan.py` — lifespan integration (extend; do NOT replace)
- `tests/knowledge_sources/test_cron_scheduler.py`

**`SchedulerSettings`:**

```python
# src/knowledge_sources/sync/scheduler.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYNC_SCHEDULER_", env_file=".env", extra="ignore")

    tick_interval_s: int = 60    # how often the scheduler wakes to evaluate due sources
    lookahead_s:     int = 60    # sources due within the next N seconds are considered due now
```

**`CronSyncScheduler`:**

```python
# src/knowledge_sources/sync/scheduler.py
import asyncio, logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from croniter import croniter
from src.connector_sdk.registry         import ConnectorRegistry
from src.knowledge_sources.repositories.knowledge_source_repository import KnowledgeSourceRepository
from src.knowledge_sources.sync.executor import SyncJobExecutor, SyncExecutorSettings

_log = logging.getLogger(__name__)

class CronSyncScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry:        ConnectorRegistry,
        settings:        SchedulerSettings | None = None,
        executor_settings: SyncExecutorSettings | None = None,
    ) -> None:
        self._session_factory   = session_factory
        self._registry          = registry
        self._settings          = settings or SchedulerSettings()
        self._executor_settings = executor_settings or SyncExecutorSettings()
        self._task: asyncio.Task | None = None

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
        now = datetime.now(tz=timezone.utc)
        async with self._session_factory() as session:
            repo    = KnowledgeSourceRepository(session)
            sources = await repo.list_active()   # returns only is_active=True records

        for source in sources:
            try:
                due = self._is_due(source.sync_schedule, source.last_sync_at, now)
            except Exception as exc:
                _log.warning("invalid_cron_expression", extra={
                    "source_id": str(source.id), "schedule": source.sync_schedule, "error": str(exc)
                })
                continue

            if due:
                _log.info("dispatching_sync", extra={
                    "source_id":      str(source.id),
                    "connector_type": source.connector_type,
                    "schedule":       source.sync_schedule,
                })
                # Fire-and-forget: sync runs in a separate task so the scheduler tick is non-blocking
                asyncio.create_task(
                    self._run_sync(source.id),
                    name = f"sync_{source.id}",
                )

    def _is_due(
        self,
        cron_expr:    str,
        last_sync_at: datetime | None,
        now:          datetime,
    ) -> bool:
        """
        Return True if the cron expression is due at `now`.
        A source with no prior sync is always considered due.
        Uses croniter to find the next scheduled time after last_sync_at.
        """
        if last_sync_at is None:
            return True
        cron = croniter(cron_expr, last_sync_at)
        next_run = cron.get_next(datetime)
        return next_run <= now

    async def _run_sync(self, source_id) -> None:
        async with self._session_factory() as session:
            executor = SyncJobExecutor(
                session  = session,
                registry = self._registry,
                settings = self._executor_settings,
            )
            try:
                await executor.run(source_id)
            except Exception as exc:
                _log.error("scheduled_sync_failed", extra={
                    "source_id": str(source_id), "error": str(exc)
                })
```

**`KnowledgeSourceRepository.list_active()` — extend existing repo:**

```python
# src/knowledge_sources/repositories/knowledge_source_repository.py  — add method
async def list_active(self) -> list[KnowledgeSourceRecord]:
    result = await self._session.execute(
        select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.is_active == True)  # noqa: E712
    )
    return list(result.scalars().all())
```

**Lifespan integration (extend existing, do NOT replace):**

```python
# src/agents/worker/lifespan.py
from src.knowledge_sources.sync.scheduler import CronSyncScheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup (registry.load(), health_poller.start()) ...
    scheduler = CronSyncScheduler(
        session_factory = app.state.db_session_factory,
        registry        = app.state.connector_registry,
    )
    scheduler.start()
    app.state.sync_scheduler = scheduler
    yield
    scheduler.stop()
```

**`session_factory` requirement:**

`CronSyncScheduler` requires an `async_sessionmaker` (not a single `AsyncSession`) because each scheduled sync run opens and closes its own session independently. Using a single shared session across multiple concurrent sync tasks would cause SQLAlchemy isolation violations.

**Due-time lookahead:**

`_is_due()` uses `next_run <= now` (exact). The 60-second tick interval means a cron expression like `*/5 * * * *` (every 5 minutes) will be triggered at most once per tick cycle, with up to 60 seconds of drift. For Phase 2 sync schedules (minutes to hours), this is acceptable.

## Acceptance Criteria

- [ ] `_is_due()` returns `True` when `last_sync_at=None` (first-ever sync)
- [ ] `_is_due()` returns `True` when `croniter.get_next(last_sync_at) <= now`
- [ ] `_is_due()` returns `False` when the next scheduled time is in the future
- [ ] Invalid cron expression is logged and skipped — tick does not raise
- [ ] Each due source triggers an independent `asyncio.create_task` (no blocking the tick loop)
- [ ] `start()` is idempotent — calling twice does not create a second task
- [ ] `stop()` cancels the task; `CancelledError` does not propagate to the event loop

## Dependencies

- TASK-US026-01 (`SyncJobRepository`)
- TASK-US026-02 (`SyncJobExecutor.run()`)
- TASK-US025-01 (`KnowledgeSourceRepository`, `KnowledgeSourceRecord.sync_schedule`)
- TASK-US021-02 (`ConnectorRegistry`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `croniter>=1.4` added to `requirements.txt` / `pyproject.toml`
- [ ] Tests mock `SyncJobExecutor.run` and `asyncio.sleep`; no real clock advances
- [ ] `mypy --strict` passes; no `ruff` lint errors
