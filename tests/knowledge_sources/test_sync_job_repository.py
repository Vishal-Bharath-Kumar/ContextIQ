"""Unit tests for SyncJobRecord ORM and SyncJobRepository — TASK-US026-01.

All tests run against an in-memory async SQLite engine; no real PostgreSQL
connection is required.

Acceptance criteria covered:
  AC-1  SyncJobRecord inserts with status="running" and completed_at=None
  AC-2  mark_succeeded() sets status="succeeded", completed_at, duration_s, items_*
  AC-3  mark_failed() sets status="failed" and truncates error_message to 2 000 chars
  AC-4  list_by_source() returns records ordered by started_at DESC
  AC-5  get() returns None for an unknown job_id
"""
from __future__ import annotations

import datetime as dt
from collections.abc import AsyncGenerator
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

from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.models.sync_job import SyncJobRecord, SyncJobStatus
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Per-test in-memory SQLite engine with knowledge_sources + sync_jobs tables.

    Registers a ``now()`` UDF so that ``server_default=text("now()")``
    columns work under SQLite (which only exposes ``datetime('now')``,
    not ``now()``).
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _register_now_fn(dbapi_conn: object, _conn_record: object) -> None:
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
    """Per-test AsyncSession backed by in-memory SQLite."""
    factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def source_id(db_session: AsyncSession) -> object:
    """Insert a KnowledgeSourceRecord and return its id (FK for sync_jobs)."""
    record = KnowledgeSourceRecord(
        connector_type="github",
        credentials_vault_path="secret/contextiq/github/test",
        scope="test-org/test-repo",
    )
    db_session.add(record)
    await db_session.flush()
    return record.id


# ---------------------------------------------------------------------------
# SyncJobRecord ORM (no-DB construction)
# ---------------------------------------------------------------------------


class TestSyncJobRecordInstantiation:
    def test_status_enum_values(self) -> None:
        assert SyncJobStatus.RUNNING == "running"
        assert SyncJobStatus.SUCCEEDED == "succeeded"
        assert SyncJobStatus.FAILED == "failed"

    def test_explicit_id_accepted(self) -> None:
        sid = uuid4()
        job_id = uuid4()
        record = SyncJobRecord(id=job_id, source_id=sid, status=SyncJobStatus.RUNNING)
        assert record.id == job_id

    def test_completed_at_defaults_to_none(self) -> None:
        record = SyncJobRecord(source_id=uuid4(), status=SyncJobStatus.RUNNING)
        assert record.completed_at is None

    def test_error_message_defaults_to_none(self) -> None:
        record = SyncJobRecord(source_id=uuid4(), status=SyncJobStatus.RUNNING)
        assert record.error_message is None


# ---------------------------------------------------------------------------
# SyncJobRepository — DB-backed tests
# ---------------------------------------------------------------------------


class TestSyncJobRepositoryCreate:
    @pytest.mark.asyncio
    async def test_create_inserts_running_record(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        assert job.status == SyncJobStatus.RUNNING
        assert job.completed_at is None
        assert job.id is not None

    @pytest.mark.asyncio
    async def test_create_defaults_attempt_and_full_sync(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        assert job.attempt_number == 1
        assert job.is_full_sync is False

    @pytest.mark.asyncio
    async def test_create_custom_attempt_and_full_sync(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job = await repo.create(
            source_id=source_id,  # type: ignore[arg-type]
            attempt_number=3,
            is_full_sync=True,
        )
        assert job.attempt_number == 3
        assert job.is_full_sync is True


class TestSyncJobRepositoryMarkSucceeded:
    @pytest.mark.asyncio
    async def test_mark_succeeded_updates_fields(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        await repo.mark_succeeded(
            job_id=job.id,
            items_processed=42,
            items_failed=2,
            duration_s=1.23,
        )
        updated = await repo.get(job.id)
        assert updated is not None
        assert updated.status == SyncJobStatus.SUCCEEDED
        assert updated.items_processed == 42
        assert updated.items_failed == 2
        assert updated.duration_s == pytest.approx(1.23)
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_mark_succeeded_noop_for_unknown_id(
        self, db_session: AsyncSession
    ) -> None:
        repo = SyncJobRepository(db_session)
        # Should not raise; simply no-ops
        await repo.mark_succeeded(
            job_id=uuid4(), items_processed=0, items_failed=0, duration_s=0.0
        )


class TestSyncJobRepositoryMarkFailed:
    @pytest.mark.asyncio
    async def test_mark_failed_updates_fields(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        await repo.mark_failed(
            job_id=job.id,
            error_message="connection timeout",
            duration_s=0.5,
        )
        updated = await repo.get(job.id)
        assert updated is not None
        assert updated.status == SyncJobStatus.FAILED
        assert updated.error_message == "connection timeout"
        assert updated.duration_s == pytest.approx(0.5)
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_mark_failed_truncates_error_message(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        long_message = "x" * 3000
        await repo.mark_failed(job_id=job.id, error_message=long_message, duration_s=1.0)
        updated = await repo.get(job.id)
        assert updated is not None
        assert len(updated.error_message) == 2000  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_mark_failed_noop_for_unknown_id(
        self, db_session: AsyncSession
    ) -> None:
        repo = SyncJobRepository(db_session)
        await repo.mark_failed(job_id=uuid4(), error_message="err", duration_s=0.0)


class TestSyncJobRepositoryGet:
    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_id(
        self, db_session: AsyncSession
    ) -> None:
        repo = SyncJobRepository(db_session)
        result = await repo.get(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_existing_record(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        fetched = await repo.get(job.id)
        assert fetched is not None
        assert fetched.id == job.id


class TestSyncJobRepositoryListBySource:
    @pytest.mark.asyncio
    async def test_list_by_source_ordered_desc(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        job1 = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        job2 = await repo.create(source_id=source_id)  # type: ignore[arg-type]
        # Set distinct started_at values so ordering is deterministic
        job1.started_at = dt.datetime(2026, 7, 1, 0, 0, 0, tzinfo=dt.UTC)
        job2.started_at = dt.datetime(2026, 7, 2, 0, 0, 0, tzinfo=dt.UTC)
        await db_session.flush()

        results = await repo.list_by_source(source_id)  # type: ignore[arg-type]
        assert len(results) == 2
        assert results[0].id == job2.id  # most recent first
        assert results[1].id == job1.id

    @pytest.mark.asyncio
    async def test_list_by_source_respects_limit(
        self, db_session: AsyncSession, source_id: object
    ) -> None:
        repo = SyncJobRepository(db_session)
        for _ in range(5):
            await repo.create(source_id=source_id)  # type: ignore[arg-type]

        results = await repo.list_by_source(source_id, limit=3)  # type: ignore[arg-type]
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_list_by_source_empty_for_unknown_source(
        self, db_session: AsyncSession
    ) -> None:
        repo = SyncJobRepository(db_session)
        results = await repo.list_by_source(uuid4())
        assert results == []
