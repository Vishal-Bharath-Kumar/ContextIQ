"""Unit tests for SyncJobExecutor — TASK-US026-02.

All tests use in-memory SQLite for DB operations and AsyncMock for
ConnectorRegistry, connector.sync(), and the Kafka producer.
asyncio.sleep is patched to avoid real delays in retry tests.

Acceptance criteria covered:
  AC-1  First successful attempt: job.status = "succeeded", Kafka event emitted,
        metrics recorded
  AC-2  One failure then success: job.attempt_number = 2, status = "succeeded",
        1 retry metric inc
  AC-3  Three failures: job.status = "failed", source.status = "error",
        no Kafka event emitted
  AC-4  Backoff waits are 2 s, 4 s, 8 s (mocked asyncio.sleep call args verified)
  AC-5  sync_duration_seconds histogram observes elapsed time with correct labels
  AC-6  sync_document_count_delta counter increments by items_processed on success
  AC-7  run() returns the job_id UUID in all paths (success and exhausted failure)
"""
from __future__ import annotations

import datetime as dt
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.connector_sdk.registry import ConnectorRegistry
from src.connector_sdk.schemas.sync import SyncResult
from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.models.sync_job import SyncJobRecord, SyncJobStatus
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository
from src.knowledge_sources.sync.executor import SyncExecutorSettings, SyncJobExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = dt.datetime(2026, 7, 16, 12, 0, 0, tzinfo=dt.UTC)

_DEFAULT_SYNC_RESULT = SyncResult(
    items_processed=42,
    items_failed=0,
    last_sync_at=_NOW,
)


def _make_registry(connector: object) -> ConnectorRegistry:
    registry = MagicMock(spec=ConnectorRegistry)
    registry.get.return_value = connector
    return registry


def _make_connector(sync_result: SyncResult | None = None) -> AsyncMock:
    connector = AsyncMock()
    connector.sync.return_value = sync_result or _DEFAULT_SYNC_RESULT
    return connector


def _patch_build_connector(executor: SyncJobExecutor, connector: object):
    """Return a patch that makes _build_connector_for_source return *connector*.

    Use inside each test's ``with (...)`` block to avoid hitting real Vault
    from the per-source connector builder introduced in executor.py.
    """
    return patch.object(
        executor,
        "_build_connector_for_source",
        new=AsyncMock(return_value=connector),
    )


# Fast settings — tiny backoff_base_s so mocked sleep args still match spec
_FAST_SETTINGS = SyncExecutorSettings(
    max_retries=3,
    backoff_base_s=2.0,
    kafka_topic="knowledge.source.synced",
)


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
    record = KnowledgeSourceRecord(
        connector_type="github",
        credentials_vault_path="secret/contextiq/github/test",
        scope="test-org/test-repo",
        document_count=0,
    )
    db_session.add(record)
    await db_session.flush()
    return record


# ---------------------------------------------------------------------------
# AC-1: First successful attempt
# ---------------------------------------------------------------------------


class TestSyncJobExecutorSuccess:
    async def test_run_returns_job_id(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            job_id = await executor.run(source_record.id)

        assert isinstance(job_id, UUID)

    async def test_job_status_succeeded_on_first_attempt(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            job_id = await executor.run(source_record.id)

        job_repo = SyncJobRepository(db_session)
        job = await job_repo.get(job_id)
        assert job is not None
        assert job.status == SyncJobStatus.SUCCEEDED
        assert job.attempt_number == 1

    async def test_source_status_active_after_success(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            await executor.run(source_record.id)

        await db_session.refresh(source_record)
        assert source_record.status == "active"

    async def test_kafka_event_emitted_on_success(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)
        emit_mock = AsyncMock()

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch.object(executor, "_emit_synced_event", emit_mock),
        ):
            await executor.run(source_record.id)

        emit_mock.assert_awaited_once()

    async def test_document_count_incremented_on_success(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            await executor.run(source_record.id)

        await db_session.refresh(source_record)
        assert source_record.document_count == _DEFAULT_SYNC_RESULT.items_processed


# ---------------------------------------------------------------------------
# AC-2: One failure then success
# ---------------------------------------------------------------------------


class TestSyncJobExecutorOneRetry:
    async def test_attempt_number_2_after_one_failure(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = [RuntimeError("transient"), _DEFAULT_SYNC_RESULT]
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total") as retry_ctr,
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            job_id = await executor.run(source_record.id)
            retry_ctr.labels.return_value.inc.assert_called_once()

        job_repo = SyncJobRepository(db_session)
        job = await job_repo.get(job_id)
        assert job is not None
        assert job.status == SyncJobStatus.SUCCEEDED
        assert job.attempt_number == 2

    async def test_kafka_event_emitted_after_retry_success(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = [RuntimeError("transient"), _DEFAULT_SYNC_RESULT]
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)
        emit_mock = AsyncMock()

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch.object(executor, "_emit_synced_event", emit_mock),
        ):
            await executor.run(source_record.id)

        emit_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# AC-3: All retries exhausted
# ---------------------------------------------------------------------------


class TestSyncJobExecutorAllFailed:
    async def test_job_status_failed_after_all_retries(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = RuntimeError("persistent error")
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
        ):
            job_id = await executor.run(source_record.id)

        job_repo = SyncJobRepository(db_session)
        job = await job_repo.get(job_id)
        assert job is not None
        assert job.status == SyncJobStatus.FAILED

    async def test_source_status_error_after_all_retries(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = RuntimeError("persistent error")
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
        ):
            await executor.run(source_record.id)

        await db_session.refresh(source_record)
        assert source_record.status == "error"

    async def test_no_kafka_event_emitted_after_all_failures(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = RuntimeError("persistent error")
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)
        emit_mock = AsyncMock()

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch.object(executor, "_emit_synced_event", emit_mock),
        ):
            await executor.run(source_record.id)

        emit_mock.assert_not_awaited()

    async def test_run_returns_job_id_on_failure(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = RuntimeError("persistent error")
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
        ):
            job_id = await executor.run(source_record.id)

        assert isinstance(job_id, UUID)


# ---------------------------------------------------------------------------
# AC-4: Backoff wait amounts (2 s, 4 s, 8 s)
# ---------------------------------------------------------------------------


class TestSyncJobExecutorBackoff:
    async def test_backoff_waits_are_correct(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = RuntimeError("always fails")
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        sleep_mock = AsyncMock()
        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", sleep_mock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
        ):
            await executor.run(source_record.id)

        # 4 total attempts → 3 sleeps for retries 2, 3, 4
        call_args = [c.args[0] for c in sleep_mock.call_args_list]
        assert call_args == [2.0, 4.0, 8.0]


# ---------------------------------------------------------------------------
# AC-5 & AC-6: Prometheus metrics
# ---------------------------------------------------------------------------


class TestSyncJobExecutorMetrics:
    async def test_duration_histogram_observed_on_success(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        duration_hist = MagicMock()
        duration_hist.labels.return_value.observe = MagicMock()
        doc_counter = MagicMock()

        with (
            _patch_build_connector(executor, connector),
            patch(
                "src.knowledge_sources.sync.executor.sync_duration_seconds",
                duration_hist,
            ),
            patch(
                "src.knowledge_sources.sync.executor.sync_document_count_delta",
                doc_counter,
            ),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            await executor.run(source_record.id)

        duration_hist.labels.assert_called_with(
            connector_type="github", status="succeeded"
        )
        duration_hist.labels.return_value.observe.assert_called_once()

    async def test_document_count_counter_incremented_on_success(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        doc_counter = MagicMock()
        doc_counter.labels.return_value.inc = MagicMock()

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch(
                "src.knowledge_sources.sync.executor.sync_document_count_delta",
                doc_counter,
            ),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            await executor.run(source_record.id)

        doc_counter.labels.assert_called_with(connector_type="github")
        doc_counter.labels.return_value.inc.assert_called_once_with(
            _DEFAULT_SYNC_RESULT.items_processed
        )

    async def test_duration_histogram_observed_on_failure(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = RuntimeError("oops")
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        duration_hist = MagicMock()

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "src.knowledge_sources.sync.executor.sync_duration_seconds",
                duration_hist,
            ),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
        ):
            await executor.run(source_record.id)

        # One failed label call per attempt (4 total: initial + 3 retries)
        failed_calls = [
            c
            for c in duration_hist.labels.call_args_list
            if c.kwargs.get("status") == "failed"
        ]
        assert len(failed_calls) == 4


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSyncJobExecutorEdgeCases:
    async def test_raises_when_source_not_found(
        self, db_session: AsyncSession
    ) -> None:
        registry = _make_registry(_make_connector())
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with pytest.raises(ValueError, match="not found"):
            await executor.run(uuid4())

    async def test_raises_when_connector_not_registered(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        registry = MagicMock(spec=ConnectorRegistry)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            patch.object(
                executor,
                "_build_connector_for_source",
                AsyncMock(side_effect=ValueError("No connector implementation for 'github'")),
            ),
            pytest.raises(ValueError, match="No connector implementation"),
        ):
            await executor.run(source_record.id)

    async def test_sync_count_4_calls_total_for_3_retries(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = AsyncMock()
        connector.sync.side_effect = RuntimeError("fail")
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.asyncio.sleep", new_callable=AsyncMock),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
        ):
            await executor.run(source_record.id)

        assert connector.sync.call_count == 4  # 1 initial + 3 retries

    async def test_run_existing_job_reuses_queued_job(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        connector = _make_connector()
        registry = _make_registry(connector)
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)
        job_repo = SyncJobRepository(db_session)
        queued_job = await job_repo.create(
            source_id=source_record.id,
            attempt_number=1,
            is_full_sync=True,
        )
        await db_session.commit()

        with (
            _patch_build_connector(executor, connector),
            patch("src.knowledge_sources.sync.executor.sync_duration_seconds"),
            patch("src.knowledge_sources.sync.executor.sync_document_count_delta"),
            patch("src.knowledge_sources.sync.executor.sync_retries_total"),
            patch(
                "src.knowledge_sources.sync.executor.SyncJobExecutor._emit_synced_event",
                new_callable=AsyncMock,
            ),
        ):
            returned_job_id = await executor.run_existing_job(
                source_id=source_record.id,
                job_id=queued_job.id,
                is_full_sync=True,
            )

        jobs = await job_repo.list_by_source(source_record.id)

        assert returned_job_id == queued_job.id
        assert len(jobs) == 1
        assert jobs[0].id == queued_job.id
        assert jobs[0].status == SyncJobStatus.SUCCEEDED

    async def test_run_existing_job_marks_failed_when_setup_raises(
        self, db_session: AsyncSession, source_record: KnowledgeSourceRecord
    ) -> None:
        registry = _make_registry(AsyncMock())
        executor = SyncJobExecutor(db_session, registry, _FAST_SETTINGS)
        job_repo = SyncJobRepository(db_session)
        queued_job = await job_repo.create(
            source_id=source_record.id,
            attempt_number=1,
            is_full_sync=True,
        )
        await db_session.commit()

        with patch.object(
            executor,
            "_build_connector_for_source",
            new=AsyncMock(side_effect=RuntimeError("bad credential")),
        ):
            with pytest.raises(RuntimeError, match="bad credential"):
                await executor.run_existing_job(
                    source_id=source_record.id,
                    job_id=queued_job.id,
                    is_full_sync=True,
                )

        job = await job_repo.get(queued_job.id)
        await db_session.refresh(source_record)

        assert job is not None
        assert job.status == SyncJobStatus.FAILED
        assert job.error_message == "bad credential"
        assert source_record.status == "error"
