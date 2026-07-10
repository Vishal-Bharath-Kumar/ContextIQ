# TASK-US026-02 — `SyncJobExecutor`: Retry Orchestration, Kafka Event, and Prometheus Metrics

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US026-02 |
| User Story | US-026 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `SyncJobExecutor` — the component that runs a single sync job for a given knowledge source, handling up to 3 retry attempts with exponential backoff (AC-4), emitting a `knowledge.source.synced` Kafka event on success (AC-5), and recording sync duration and document count delta as Prometheus metrics (AC-7).

## Implementation Details

**Technology:** Python 3.11+, `aiokafka`, `prometheus-client>=0.20`, `asyncio`

**File locations:**
- `src/knowledge_sources/sync/executor.py` — `SyncJobExecutor`, `SyncExecutorSettings`
- `src/knowledge_sources/sync/metrics.py` — Prometheus metrics
- `tests/knowledge_sources/test_sync_executor.py`

**Prometheus metrics (AC-7):**

```python
# src/knowledge_sources/sync/metrics.py
from prometheus_client import Histogram, Counter, Gauge

sync_duration_seconds = Histogram(
    "knowledge_source_sync_duration_seconds",
    "Duration of a completed knowledge source sync job",
    ["connector_type", "status"],   # status: "succeeded" | "failed"
    buckets=[1, 5, 15, 30, 60, 120, 300],
)

sync_document_count_delta = Counter(
    "knowledge_source_sync_documents_total",
    "Cumulative documents processed across all sync jobs",
    ["connector_type"],
)

sync_retries_total = Counter(
    "knowledge_source_sync_retries_total",
    "Number of sync retry attempts",
    ["connector_type"],
)
```

**`SyncExecutorSettings`:**

```python
# src/knowledge_sources/sync/executor.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class SyncExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYNC_EXECUTOR_", env_file=".env", extra="ignore")

    max_retries:    int   = 3      # US-026 AC-4
    backoff_base_s: float = 2.0   # wait = backoff_base_s ^ attempt (2, 4, 8 s)
    kafka_topic:    str   = "knowledge.source.synced"
```

**`SyncJobExecutor`:**

```python
# src/knowledge_sources/sync/executor.py
import asyncio, json, logging, time
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from src.connector_sdk.registry         import ConnectorRegistry
from src.knowledge_sources.repositories.knowledge_source_repository import KnowledgeSourceRepository
from src.knowledge_sources.repositories.sync_job_repository         import SyncJobRepository
from src.knowledge_sources.sync.metrics import (
    sync_duration_seconds, sync_document_count_delta, sync_retries_total,
)
from src.knowledge_sources.schemas.knowledge_source import SourceStatus

_log = logging.getLogger(__name__)

class SyncJobExecutor:
    def __init__(
        self,
        session:   AsyncSession,
        registry:  ConnectorRegistry,
        settings:  SyncExecutorSettings | None = None,
    ) -> None:
        self._session  = session
        self._registry = registry
        self._settings = settings or SyncExecutorSettings()

    async def run(self, source_id: UUID, is_full_sync: bool = False) -> UUID:
        """
        Execute a sync job for source_id with retry logic.
        Returns the sync job ID (for on-demand callers to poll status).
        """
        source_repo = KnowledgeSourceRepository(self._session)
        job_repo    = SyncJobRepository(self._session)
        settings    = self._settings

        source = await source_repo.get_by_id(source_id)
        if source is None:
            raise ValueError(f"Knowledge source {source_id} not found")

        connector = self._registry.get(source.connector_type)
        if connector is None:
            raise ValueError(f"No active connector registered for '{source.connector_type}'")

        # Mark source as syncing
        source.status = SourceStatus.SYNCING
        await self._session.flush()

        job = await job_repo.create(source_id=source_id, attempt_number=1, is_full_sync=is_full_sync)
        await self._session.commit()

        last_exc: Exception | None = None
        for attempt in range(1, settings.max_retries + 2):   # max_retries=3 → 4 attempts total (1 + 3 retries)
            if attempt > 1:
                wait = settings.backoff_base_s ** (attempt - 1)  # 2, 4, 8 s
                _log.warning("sync_retry", extra={"source_id": str(source_id), "attempt": attempt, "wait_s": wait})
                sync_retries_total.labels(connector_type=source.connector_type).inc()
                await asyncio.sleep(wait)

            t0 = time.perf_counter()
            try:
                # Update attempt number on retries
                if attempt > 1:
                    job.attempt_number = attempt
                    await self._session.flush()

                sync_result = await connector.sync()
                duration    = time.perf_counter() - t0

                await job_repo.mark_succeeded(
                    job_id          = job.id,
                    items_processed = sync_result.items_processed,
                    items_failed    = sync_result.items_failed,
                    duration_s      = duration,
                )
                source.status      = SourceStatus.ACTIVE
                source.last_sync_at = datetime.now(tz=timezone.utc)
                source.document_count += sync_result.items_processed
                await self._session.commit()

                # Metrics (AC-7)
                sync_duration_seconds.labels(
                    connector_type = source.connector_type, status="succeeded"
                ).observe(duration)
                sync_document_count_delta.labels(
                    connector_type = source.connector_type
                ).inc(sync_result.items_processed)

                # Kafka success event (AC-5)
                await self._emit_synced_event(source, job.id, sync_result.items_processed)
                return job.id

            except Exception as exc:
                last_exc = exc
                duration = time.perf_counter() - t0
                sync_duration_seconds.labels(
                    connector_type = source.connector_type, status="failed"
                ).observe(duration)
                _log.error("sync_attempt_failed", extra={
                    "source_id": str(source_id), "attempt": attempt, "error": str(exc)
                })

        # All attempts exhausted
        await job_repo.mark_failed(
            job_id        = job.id,
            error_message = str(last_exc),
            duration_s    = time.perf_counter() - t0,
        )
        source.status = SourceStatus.ERROR
        await self._session.commit()
        return job.id

    async def _emit_synced_event(self, source, job_id: UUID, items_processed: int) -> None:
        from src.events.producer import get_kafka_producer
        event = {
            "event_type":      "knowledge_source_synced",
            "source_id":       str(source.id),
            "job_id":          str(job_id),
            "connector_type":  source.connector_type,
            "scope":           source.scope,
            "items_processed": items_processed,
            "synced_at":       datetime.now(tz=timezone.utc).isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            self._settings.kafka_topic,
            value = json.dumps(event).encode(),
        )
```

**Retry arithmetic:**

| Attempt | Wait before attempt |
|---|---|
| 1 (initial) | 0 s |
| 2 (retry 1) | 2 s |
| 3 (retry 2) | 4 s |
| 4 (retry 3) | 8 s |

`max_retries=3` means 1 initial attempt + 3 retries = 4 total tries.

**`source.document_count` accumulation:**

`document_count += sync_result.items_processed` accumulates incremental counts. For a full sync (`is_full_sync=True`), the scheduler resets `document_count = 0` before calling `executor.run()` so the count reflects the true total after a full re-index.

## Acceptance Criteria

- [ ] First successful attempt: `job.status = "succeeded"`, Kafka event emitted, metrics recorded
- [ ] One failure then success: `job.attempt_number = 2`, `status = "succeeded"`, 1 retry metric inc
- [ ] Three failures: `job.status = "failed"`, `source.status = "error"`, no Kafka event emitted
- [ ] Backoff waits are `2 s`, `4 s`, `8 s` (mocked `asyncio.sleep` call args verified)
- [ ] `sync_duration_seconds` histogram observes elapsed time with correct `connector_type` and `status` labels
- [ ] `sync_document_count_delta` counter increments by `sync_result.items_processed` on success
- [ ] `run()` returns the `job_id` UUID in all paths (success and exhausted failure)

## Dependencies

- TASK-US026-01 (`SyncJobRepository`, `SyncJobRecord`, `SyncJobStatus`)
- TASK-US025-01 (`KnowledgeSourceRepository`, `SourceStatus`)
- TASK-US021-02 (`ConnectorRegistry.get(connector_type)`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `ConnectorRegistry`, `connector.sync()`, and Kafka producer via `AsyncMock`
- [ ] `asyncio.sleep` patched in retry tests to avoid real delays
- [ ] `mypy --strict` passes; no `ruff` lint errors
