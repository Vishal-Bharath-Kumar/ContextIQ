"""Integration tests for knowledge source sync — TASK-US026-05.

Covers all 7 US-026 acceptance criteria end-to-end using in-memory SQLite,
AsyncMock connectors, and patched Kafka/event infrastructure.

Acceptance criteria verified:
  AC-1  Scheduler reads cron expressions and dispatches due sources
  AC-2  Executor calls connector.sync()
  AC-3  Sync job status lifecycle persisted to DB (running → succeeded/failed)
  AC-4  Retry 3 times with 2 s / 4 s / 8 s exponential backoff
  AC-5  Kafka `knowledge.source.synced` event emitted on success only
  AC-6  On-demand sync endpoint returns HTTP 202 with job_id
  AC-7  Prometheus sync_document_count_delta counter incremented by items_processed
"""
from __future__ import annotations

import datetime as dt
import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.connector_sdk.schemas.sync import SyncResult
from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.models.sync_job import SyncJobRecord, SyncJobStatus
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository
from src.knowledge_sources.sync.executor import SyncExecutorSettings, SyncJobExecutor
from src.knowledge_sources.sync.metrics import sync_document_count_delta
from src.knowledge_sources.sync.scheduler import CronSyncScheduler, SchedulerSettings

# Module-level source ID shared by all tests that use the URL or mock service layer.
SOURCE_ID = uuid4()

# ---------------------------------------------------------------------------
# DB fixtures (in-memory SQLite)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _register_now_fn(dbapi_conn: object, _: object) -> None:
        assert hasattr(dbapi_conn, "create_function")
        dbapi_conn.create_function(  # type: ignore[union-attr]
            "now", 0, lambda: dt.datetime.now(dt.UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            KnowledgeSourceRecord.__table__.metadata.create_all,
            tables=[
                KnowledgeSourceRecord.__table__,
                SyncJobRecord.__table__,
            ],
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def source_record(db_session: AsyncSession) -> KnowledgeSourceRecord:
    """Insert a real KnowledgeSourceRecord into the in-memory DB."""
    record = KnowledgeSourceRecord(
        id=SOURCE_ID,
        connector_type="github",
        credentials_vault_path="secret/contextiq/github/test",
        scope="test-org/test-repo",
        document_count=0,
    )
    db_session.add(record)
    await db_session.flush()
    return record


# ---------------------------------------------------------------------------
# Connector / registry / Kafka mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sync_result() -> SyncResult:
    return SyncResult(
        items_processed=42,
        items_failed=0,
        last_sync_at=dt.datetime.now(tz=dt.UTC),
    )


@pytest.fixture
def mock_connector(mock_sync_result: SyncResult) -> AsyncMock:
    c = AsyncMock()
    c.sync = AsyncMock(return_value=mock_sync_result)
    return c


@pytest.fixture
def mock_registry(mock_connector: AsyncMock) -> MagicMock:
    r = MagicMock()
    r.get = MagicMock(return_value=mock_connector)
    return r


@pytest.fixture
def mock_kafka() -> AsyncMock:
    """Patch the Kafka producer at its source so _emit_synced_event is intercepted."""
    with patch(
        "src.events.producer.get_kafka_producer", new_callable=AsyncMock
    ) as m:
        producer = AsyncMock()
        producer.send_and_wait = AsyncMock()
        m.return_value = producer
        yield producer


# ---------------------------------------------------------------------------
# AC-1: Scheduler reads cron expressions and dispatches due sources
# ---------------------------------------------------------------------------


async def test_scheduler_reads_cron_and_dispatches_due_source(
    mock_registry: MagicMock, mock_kafka: AsyncMock
) -> None:
    """Sources with expired cron schedules trigger a sync task."""
    past_sync = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=7)
    source = MagicMock(
        id=SOURCE_ID,
        is_active=True,
        sync_schedule="0 */6 * * *",
        last_sync_at=past_sync,
        connector_type="github",
    )

    # Build a session_factory mock that supports `async with factory() as session:`
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=mock_cm)

    with patch(
        "src.knowledge_sources.repositories.knowledge_source_repository"
        ".KnowledgeSourceRepository.list_active",
        new_callable=AsyncMock,
        return_value=[source],
    ), patch("asyncio.create_task") as mock_create_task:
        scheduler = CronSyncScheduler(
            session_factory=session_factory,  # type: ignore[arg-type]
            registry=mock_registry,
            settings=SchedulerSettings(tick_interval_s=1),
        )
        await scheduler._tick()

    mock_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# AC-2: Executor calls connector.sync()
# ---------------------------------------------------------------------------


async def test_executor_calls_connector_sync(
    mock_connector: AsyncMock,
    mock_registry: MagicMock,
    mock_kafka: AsyncMock,
    db_session: AsyncSession,
    source_record: KnowledgeSourceRecord,
) -> None:
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    await executor.run(source_record.id)
    mock_connector.sync.assert_awaited_once()


# ---------------------------------------------------------------------------
# AC-3: Sync job status lifecycle in PostgreSQL (SQLite in CI)
# ---------------------------------------------------------------------------


async def test_sync_job_status_lifecycle(
    mock_connector: AsyncMock,
    mock_registry: MagicMock,
    mock_kafka: AsyncMock,
    db_session: AsyncSession,
    source_record: KnowledgeSourceRecord,
) -> None:
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    job_id = await executor.run(source_record.id)
    job_repo = SyncJobRepository(db_session)
    job = await job_repo.get(job_id)

    assert job is not None
    assert job.status == SyncJobStatus.SUCCEEDED
    assert job.completed_at is not None
    assert job.items_processed == 42


# ---------------------------------------------------------------------------
# AC-4: Retry 3 times with exponential backoff (2 s, 4 s, 8 s)
# ---------------------------------------------------------------------------


async def test_retry_3_times_exponential_backoff(
    mock_registry: MagicMock,
    mock_kafka: AsyncMock,
    db_session: AsyncSession,
    source_record: KnowledgeSourceRecord,
) -> None:
    failing_connector = AsyncMock()
    failing_connector.sync = AsyncMock(side_effect=RuntimeError("remote error"))
    mock_registry.get = MagicMock(return_value=failing_connector)

    with patch("asyncio.sleep") as mock_sleep:
        executor = SyncJobExecutor(
            session=db_session,
            registry=mock_registry,
            settings=SyncExecutorSettings(max_retries=3, backoff_base_s=2.0),
        )
        job_id = await executor.run(source_record.id)

    assert failing_connector.sync.await_count == 4  # 1 initial + 3 retries
    sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
    assert sleep_args == [2.0, 4.0, 8.0]  # backoff_base_s^1, ^2, ^3

    job_repo = SyncJobRepository(db_session)
    job = await job_repo.get(job_id)
    assert job is not None
    assert job.status == SyncJobStatus.FAILED
    assert job.attempt_number == 4


# ---------------------------------------------------------------------------
# AC-5: Kafka `knowledge.source.synced` event
# ---------------------------------------------------------------------------


async def test_kafka_synced_event_emitted_on_success(
    mock_connector: AsyncMock,
    mock_registry: MagicMock,
    mock_kafka: AsyncMock,
    db_session: AsyncSession,
    source_record: KnowledgeSourceRecord,
) -> None:
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    await executor.run(source_record.id)

    mock_kafka.send_and_wait.assert_awaited_once()
    topic = mock_kafka.send_and_wait.call_args.args[0]
    payload = json.loads(mock_kafka.send_and_wait.call_args.kwargs["value"])
    assert topic == "knowledge.source.synced"
    assert payload["event_type"] == "knowledge_source_synced"
    assert payload["items_processed"] == 42


async def test_kafka_event_NOT_emitted_on_failure(
    mock_registry: MagicMock,
    mock_kafka: AsyncMock,
    db_session: AsyncSession,
    source_record: KnowledgeSourceRecord,
) -> None:
    failing = AsyncMock()
    failing.sync = AsyncMock(side_effect=RuntimeError("fail"))
    mock_registry.get = MagicMock(return_value=failing)

    with patch("asyncio.sleep"):
        executor = SyncJobExecutor(
            session=db_session,
            registry=mock_registry,
            settings=SyncExecutorSettings(max_retries=0),
        )
        await executor.run(source_record.id)

    mock_kafka.send_and_wait.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC-6: On-demand sync endpoint returns HTTP 202 with job_id
# ---------------------------------------------------------------------------


async def test_on_demand_sync_returns_202(
    mock_registry: MagicMock, mock_kafka: AsyncMock
) -> None:
    from httpx import ASGITransport, AsyncClient

    from src.auth.dependencies import decode_jwt_claims
    from src.auth.roles import PlatformRole
    from src.auth.testing import make_test_claims
    from src.data.dependencies import get_db
    from src.knowledge_sources.dependencies import get_knowledge_source_service
    from src.main import app

    def _noop_create_task(coro: object, *, name: str | None = None) -> MagicMock:
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]
        return MagicMock()

    job = MagicMock()
    job.id = uuid4()
    svc = MagicMock()
    svc._repo.get_by_id = AsyncMock(return_value=MagicMock())
    mock_session = AsyncMock()
    admin_claims = make_test_claims(PlatformRole.ADMIN)

    app.dependency_overrides[decode_jwt_claims] = lambda: admin_claims
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        with (
            patch(
                "src.knowledge_sources.routers.knowledge_source_router.SyncJobRepository"
            ) as mock_repo_cls,
            patch("asyncio.create_task", side_effect=_noop_create_task),
        ):
            mock_repo = AsyncMock()
            mock_repo.create.return_value = job
            mock_repo_cls.return_value = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/v1/knowledge-sources/{SOURCE_ID}/sync",
                )

        assert resp.status_code == 202
        assert "job_id" in resp.json()
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-7: Prometheus sync_document_count_delta counter incremented
# ---------------------------------------------------------------------------


async def test_prometheus_metrics_recorded(
    mock_connector: AsyncMock,
    mock_registry: MagicMock,
    mock_kafka: AsyncMock,
    db_session: AsyncSession,
    source_record: KnowledgeSourceRecord,
) -> None:
    before = sync_document_count_delta.labels(connector_type="github")._value.get()
    executor = SyncJobExecutor(session=db_session, registry=mock_registry)
    await executor.run(source_record.id)
    after = sync_document_count_delta.labels(connector_type="github")._value.get()
    assert after - before == 42  # items_processed from mock_sync_result
