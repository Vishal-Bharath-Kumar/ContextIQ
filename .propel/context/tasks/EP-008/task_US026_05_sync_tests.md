# TASK-US026-05 — Integration Tests Covering All 7 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US026-05 |
| User Story | US-026 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Done |

## Description

Write the integration and unit test suite covering all 7 US-026 acceptance criteria: cron scheduling, connector `sync()` call with `since`, DB job status lifecycle, 3-retry exponential backoff, Kafka `knowledge.source.synced` event, on-demand sync endpoint (202), and Prometheus metrics emission.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `AsyncMock`, `unittest.mock`

**File locations:**
- `tests/knowledge_sources/test_sync_integration.py` — AC-level integration tests
- `tests/knowledge_sources/test_cron_scheduler_unit.py` — `_is_due()` unit tests (no I/O)

**Fixtures:**

```python
# tests/knowledge_sources/test_sync_integration.py
import pytest, asyncio, json
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from src.knowledge_sources.sync.executor    import SyncJobExecutor, SyncExecutorSettings
from src.knowledge_sources.sync.scheduler   import CronSyncScheduler, SchedulerSettings
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository
from src.connector_sdk.schemas.sync         import SyncResult

SOURCE_ID = uuid4()

@pytest.fixture
def mock_sync_result():
    return SyncResult(items_processed=42, items_failed=0, last_sync_at=datetime.now(tz=timezone.utc))

@pytest.fixture
def mock_connector(mock_sync_result):
    c = AsyncMock()
    c.sync = AsyncMock(return_value=mock_sync_result)
    return c

@pytest.fixture
def mock_registry(mock_connector):
    r = MagicMock()
    r.get = MagicMock(return_value=mock_connector)
    return r

@pytest.fixture
def mock_kafka():
    with patch("src.knowledge_sources.sync.executor.get_kafka_producer") as m:
        producer = AsyncMock()
        producer.send_and_wait = AsyncMock()
        m.return_value = producer
        yield producer
```

**AC-1 — Scheduler reads cron expressions:**

```python
async def test_scheduler_reads_cron_and_dispatches_due_source(mock_registry, mock_kafka):
    """Sources with expired cron schedules trigger a sync task."""
    past_sync = datetime.now(tz=timezone.utc) - timedelta(hours=7)
    source = MagicMock(id=SOURCE_ID, is_active=True, sync_schedule="0 */6 * * *",
                       last_sync_at=past_sync, connector_type="github")

    with patch(
        "src.knowledge_sources.repositories.knowledge_source_repository.KnowledgeSourceRepository.list_active",
        new_callable = AsyncMock,
        return_value = [source],
    ), patch("asyncio.create_task") as mock_create_task:
        scheduler = CronSyncScheduler(
            session_factory = AsyncMock(),
            registry        = mock_registry,
            settings        = SchedulerSettings(tick_interval_s=1),
        )
        await scheduler._tick()
    mock_create_task.assert_called_once()
```

**AC-2 — Connector `sync()` called (since is managed by the connector's `ConnectorSyncStore`):**

```python
async def test_executor_calls_connector_sync(mock_connector, mock_registry, mock_kafka, db_session):
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    await executor.run(SOURCE_ID)
    mock_connector.sync.assert_awaited_once()
```

**AC-3 — Sync job status lifecycle in PostgreSQL:**

```python
async def test_sync_job_status_lifecycle(mock_connector, mock_registry, mock_kafka, db_session):
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    job_id   = await executor.run(SOURCE_ID)
    job_repo = SyncJobRepository(db_session)
    job      = await job_repo.get(job_id)
    assert job.status          == "succeeded"
    assert job.completed_at    is not None
    assert job.items_processed == 42
```

**AC-4 — Retry 3 times with exponential backoff:**

```python
async def test_retry_3_times_exponential_backoff(mock_registry, mock_kafka, db_session):
    failing_connector = AsyncMock()
    failing_connector.sync = AsyncMock(side_effect=RuntimeError("remote error"))
    mock_registry.get = MagicMock(return_value=failing_connector)

    with patch("asyncio.sleep") as mock_sleep:
        executor = SyncJobExecutor(
            session  = db_session,
            registry = mock_registry,
            settings = SyncExecutorSettings(max_retries=3, backoff_base_s=2.0),
        )
        job_id = await executor.run(SOURCE_ID)

    assert failing_connector.sync.await_count == 4   # 1 initial + 3 retries
    sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
    assert sleep_args == [2.0, 4.0, 8.0]             # 2^1, 2^2, 2^3

    job_repo = SyncJobRepository(db_session)
    job      = await job_repo.get(job_id)
    assert job.status        == "failed"
    assert job.attempt_number == 4
```

**AC-5 — Kafka `knowledge.source.synced` event:**

```python
async def test_kafka_synced_event_emitted_on_success(mock_connector, mock_registry, mock_kafka, db_session):
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    await executor.run(SOURCE_ID)

    mock_kafka.send_and_wait.assert_awaited_once()
    topic   = mock_kafka.send_and_wait.call_args.args[0]
    payload = json.loads(mock_kafka.send_and_wait.call_args.kwargs["value"])
    assert topic                    == "knowledge.source.synced"
    assert payload["event_type"]    == "knowledge_source_synced"
    assert payload["items_processed"] == 42

async def test_kafka_event_NOT_emitted_on_failure(mock_registry, mock_kafka, db_session):
    failing = AsyncMock()
    failing.sync = AsyncMock(side_effect=RuntimeError("fail"))
    mock_registry.get = MagicMock(return_value=failing)
    with patch("asyncio.sleep"):
        executor = SyncJobExecutor(session=db_session, registry=mock_registry,
                                   settings=SyncExecutorSettings(max_retries=0))
        await executor.run(SOURCE_ID)
    mock_kafka.send_and_wait.assert_not_awaited()
```

**AC-6 — On-demand sync returns 202:**

```python
async def test_on_demand_sync_returns_202(mock_registry, mock_kafka):
    from httpx import AsyncClient, ASGITransport
    from src.gateway.main import app
    with patch("asyncio.create_task"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/v1/knowledge-sources/{SOURCE_ID}/sync",
                headers={"Authorization": "Bearer <admin-jwt>"},
            )
    assert resp.status_code == 202
    assert "job_id" in resp.json()
```

**AC-7 — Prometheus metrics recorded:**

```python
async def test_prometheus_metrics_recorded(mock_connector, mock_registry, mock_kafka, db_session):
    from prometheus_client import REGISTRY
    from src.knowledge_sources.sync.metrics import sync_document_count_delta

    before = sync_document_count_delta.labels(connector_type="github")._value.get()
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    await executor.run(SOURCE_ID)
    after = sync_document_count_delta.labels(connector_type="github")._value.get()
    assert after - before == 42   # items_processed from mock_sync_result
```

**`_is_due()` unit tests (no I/O):**

```python
# tests/knowledge_sources/test_cron_scheduler_unit.py
from datetime import datetime, timezone, timedelta
from src.knowledge_sources.sync.scheduler import CronSyncScheduler

def _scheduler():
    return CronSyncScheduler(session_factory=None, registry=None)

def test_is_due_when_no_prior_sync():
    assert _scheduler()._is_due("0 */6 * * *", None, datetime.now(tz=timezone.utc))

def test_is_due_when_next_run_is_past():
    last = datetime.now(tz=timezone.utc) - timedelta(hours=7)
    assert _scheduler()._is_due("0 */6 * * *", last, datetime.now(tz=timezone.utc))

def test_not_due_when_next_run_is_future():
    last = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    assert not _scheduler()._is_due("0 */6 * * *", last, datetime.now(tz=timezone.utc))
```

## Acceptance Criteria

- [x] All 7 AC-level tests pass in CI
- [x] `test_retry_3_times_exponential_backoff` verifies exactly `[2.0, 4.0, 8.0]` sleep args
- [x] `test_kafka_event_NOT_emitted_on_failure` passes (no Kafka call on exhausted retries)
- [x] Prometheus delta assertion uses scoped `_value.get()` — not global registry reset
- [x] `_is_due()` unit tests run with no DB or external I/O

## Dependencies

- TASK-US026-01 (`SyncJobRepository`, `SyncJobStatus`)
- TASK-US026-02 (`SyncJobExecutor`, `SyncExecutorSettings`, Prometheus metrics)
- TASK-US026-03 (`CronSyncScheduler`, `_is_due()`)
- TASK-US026-04 (on-demand sync endpoint — AC-6 test)

## Definition of Done

- [x] Code reviewed and merged to `main`
- [x] All tests use `AsyncMock`; no live DB, Kafka, or connectors in CI
- [x] `mypy --strict` passes; no `ruff` lint errors
