"""Unit tests for KnowledgeSourceService — TASK-US025-03.

Tests run against an in-memory async SQLite engine; VaultPathValidator and the
Kafka producer are replaced with AsyncMock/MagicMock so no external services
are required.

Acceptance criteria covered:
  AC-1  create() raises HTTP 400 when VaultPathValidator returns valid=False
  AC-2  create() raises HTTP 409 when (connector_type, scope) already exists
  AC-3  409 guard fires before Vault validation is called on duplicate
  AC-4  create() commits the DB record before emitting the Kafka event
  AC-5  list_all() returns records ordered by created_at DESC
  AC-6  toggle_active(id, False) sets is_active=False and status="inactive"
  AC-7  toggle_active(unknown_id, ...) raises HTTP 404
"""
from __future__ import annotations

import datetime as dt
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.schemas.knowledge_source import (
    ConnectorType,
    KnowledgeSourceCreate,
    SourceStatus,
)
from src.knowledge_sources.services.knowledge_source_service import (
    KnowledgeSourceService,
)
from src.knowledge_sources.vault_validator import VaultValidationResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_PAYLOAD = KnowledgeSourceCreate(
    name="Acme GitHub",
    connector_type=ConnectorType.GITHUB,
    credentials_vault_path="secret/contextiq/github/acme",
    scope="acme-org/api-service",
    sync_schedule="0 */6 * * *",
    token_budget_weight=1.0,
)

_PAYLOAD_WITH_CREDENTIAL = KnowledgeSourceCreate(
    name="Acme GitHub",
    connector_type=ConnectorType.GITHUB,
    credentials_vault_path="connectors/github/acme",
    credential_value="ghp_real_token_value",
    scope="acme-org/api-service",
    sync_schedule="0 */6 * * *",
    token_budget_weight=1.0,
)


def _ok_validator() -> AsyncMock:
    """VaultPathValidator that always returns valid=True."""
    mock = AsyncMock()
    mock.validate = AsyncMock(
        return_value=VaultValidationResult(valid=True, message="Path exists")
    )
    return mock


def _fail_validator(message: str = "Path not found") -> AsyncMock:
    """VaultPathValidator that always returns valid=False."""
    mock = AsyncMock()
    mock.validate = AsyncMock(
        return_value=VaultValidationResult(valid=False, message=message)
    )
    return mock


def _ok_writer() -> AsyncMock:
    """VaultCredentialWriter that always returns valid=True."""
    mock = AsyncMock()
    mock.write = AsyncMock(
        return_value=VaultValidationResult(valid=True, message="Credential stored in Vault")
    )
    return mock


def _fail_writer(message: str = "Vault write failed") -> AsyncMock:
    """VaultCredentialWriter that always returns valid=False."""
    mock = AsyncMock()
    mock.write = AsyncMock(
        return_value=VaultValidationResult(valid=False, message=message)
    )
    return mock


def _mock_kafka_producer() -> MagicMock:
    """Async-compatible Kafka producer mock."""
    producer = MagicMock()
    producer.send_and_wait = AsyncMock(return_value=None)
    return producer


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Per-test in-memory SQLite engine with only the knowledge_sources table.

    Creates only the tables needed for this test module so PostgreSQL-specific
    types in other models (e.g. JSONB in connector_config) do not cause errors.

    Registers a ``now()`` UDF so that the ``server_default=text("now()")``
    columns on KnowledgeSourceRecord work in SQLite (which only has
    ``datetime('now')``, not ``now()``).
    """
    from sqlalchemy import event as sa_event

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
            tables=[KnowledgeSourceRecord.__table__],
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_source(
    session: AsyncSession,
    connector_type: str = "github",
    scope: str = "acme-org/api-service",
    created_offset: int = 0,
) -> KnowledgeSourceRecord:
    """Insert a KnowledgeSourceRecord directly, bypassing service logic."""
    record = KnowledgeSourceRecord(
        connector_type=connector_type,
        credentials_vault_path="secret/test/path",
        scope=scope,
        sync_schedule="0 */6 * * *",
        token_budget_weight=1.0,
        status="active",
        is_active=True,
        created_at=dt.datetime(2026, 7, 16, 12, 0, created_offset, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 7, 16, 12, 0, created_offset, tzinfo=dt.UTC),
    )
    session.add(record)
    await session.flush()
    await session.commit()
    return record


# ---------------------------------------------------------------------------
# AC-1: HTTP 400 on Vault validation failure
# ---------------------------------------------------------------------------


class TestCreateVaultValidation:
    @pytest.mark.asyncio
    async def test_raises_400_when_vault_invalid(
        self, db_session: AsyncSession
    ) -> None:
        svc = KnowledgeSourceService(
            session=db_session,
            validator=_fail_validator("Vault path does not exist"),
        )
        with pytest.raises(HTTPException) as exc_info:
            await svc.create(_VALID_PAYLOAD)

        assert exc_info.value.status_code == 400
        assert "Vault path does not exist" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_no_db_write_when_vault_invalid(
        self, db_session: AsyncSession
    ) -> None:
        svc = KnowledgeSourceService(
            session=db_session,
            validator=_fail_validator(),
        )
        with pytest.raises(HTTPException):
            await svc.create(_VALID_PAYLOAD)

        # Nothing persisted
        from sqlalchemy import select
        result = await db_session.execute(select(KnowledgeSourceRecord))
        assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# credential_value: writes to Vault instead of requiring the path to pre-exist
# ---------------------------------------------------------------------------


class TestCreateWithCredentialValue:
    @pytest.mark.asyncio
    async def test_writes_credential_to_vault_instead_of_validating_path(
        self, db_session: AsyncSession
    ) -> None:
        writer = _ok_writer()
        validator = _ok_validator()
        kafka_mock = _mock_kafka_producer()
        with patch(
            "src.events.producer.get_kafka_producer",
            new=AsyncMock(return_value=kafka_mock),
        ):
            svc = KnowledgeSourceService(
                session=db_session, validator=validator, writer=writer
            )
            response = await svc.create(_PAYLOAD_WITH_CREDENTIAL)

        writer.write.assert_awaited_once_with(
            "connectors/github/acme", "ghp_real_token_value"
        )
        validator.validate.assert_not_awaited()
        assert response.scope == "acme-org/api-service"

    @pytest.mark.asyncio
    async def test_raises_400_when_vault_write_fails(
        self, db_session: AsyncSession
    ) -> None:
        writer = _fail_writer("Vault path exists but platform role lacks write permission")
        svc = KnowledgeSourceService(session=db_session, writer=writer)

        with pytest.raises(HTTPException) as exc_info:
            await svc.create(_PAYLOAD_WITH_CREDENTIAL)

        assert exc_info.value.status_code == 400
        assert "lacks write permission" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_no_db_write_when_vault_write_fails(
        self, db_session: AsyncSession
    ) -> None:
        writer = _fail_writer()
        svc = KnowledgeSourceService(session=db_session, writer=writer)

        with pytest.raises(HTTPException):
            await svc.create(_PAYLOAD_WITH_CREDENTIAL)

        from sqlalchemy import select
        result = await db_session.execute(select(KnowledgeSourceRecord))
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_falls_back_to_validator_when_credential_value_omitted(
        self, db_session: AsyncSession
    ) -> None:
        """Backward compatible: without credential_value, path-exists validation still runs."""
        writer = _ok_writer()
        validator = _ok_validator()
        kafka_mock = _mock_kafka_producer()
        with patch(
            "src.events.producer.get_kafka_producer",
            new=AsyncMock(return_value=kafka_mock),
        ):
            svc = KnowledgeSourceService(
                session=db_session, validator=validator, writer=writer
            )
            await svc.create(_VALID_PAYLOAD)

        validator.validate.assert_awaited_once()
        writer.write.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC-2 & AC-3: HTTP 409 on duplicate (connector_type, scope)
# ---------------------------------------------------------------------------


class TestCreateDuplicateGuard:
    @pytest.mark.asyncio
    async def test_raises_409_on_duplicate(self, db_session: AsyncSession) -> None:
        await _insert_source(
            db_session,
            connector_type="github",
            scope="acme-org/api-service",
        )
        svc = KnowledgeSourceService(
            session=db_session,
            validator=_ok_validator(),
        )
        with pytest.raises(HTTPException) as exc_info:
            await svc.create(_VALID_PAYLOAD)

        assert exc_info.value.status_code == 409
        assert "github" in exc_info.value.detail
        assert "acme-org/api-service" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_409_fires_after_vault_validation(
        self, db_session: AsyncSession
    ) -> None:
        """Per spec: Vault validation is called first; 409 check comes second."""
        await _insert_source(
            db_session,
            connector_type="github",
            scope="acme-org/api-service",
        )
        validator = _ok_validator()
        svc = KnowledgeSourceService(session=db_session, validator=validator)

        with pytest.raises(HTTPException) as exc_info:
            await svc.create(_VALID_PAYLOAD)

        assert exc_info.value.status_code == 409
        # Vault validate was still called
        validator.validate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_different_scope_does_not_conflict(
        self, db_session: AsyncSession
    ) -> None:
        await _insert_source(
            db_session,
            connector_type="github",
            scope="other-org/other-repo",
        )
        kafka_mock = _mock_kafka_producer()
        with patch(
            "src.events.producer.get_kafka_producer",
            new=AsyncMock(return_value=kafka_mock),
        ):
            svc = KnowledgeSourceService(
                session=db_session,
                validator=_ok_validator(),
            )
            response = await svc.create(_VALID_PAYLOAD)

        assert response.scope == "acme-org/api-service"


# ---------------------------------------------------------------------------
# AC-4: DB commit before Kafka event
# ---------------------------------------------------------------------------


class TestCreateCommitBeforeKafka:
    @pytest.mark.asyncio
    async def test_successful_create_returns_response(
        self, db_session: AsyncSession
    ) -> None:
        kafka_mock = _mock_kafka_producer()
        with patch(
            "src.events.producer.get_kafka_producer",
            new=AsyncMock(return_value=kafka_mock),
        ):
            svc = KnowledgeSourceService(
                session=db_session,
                validator=_ok_validator(),
            )
            response = await svc.create(_VALID_PAYLOAD)

        assert response.connector_type == ConnectorType.GITHUB
        assert response.scope == "acme-org/api-service"
        assert response.is_active is True
        assert response.status == SourceStatus.ACTIVE
        assert response.id is not None

    @pytest.mark.asyncio
    async def test_kafka_event_emitted_on_create(
        self, db_session: AsyncSession
    ) -> None:
        kafka_mock = _mock_kafka_producer()
        with patch(
            "src.events.producer.get_kafka_producer",
            new=AsyncMock(return_value=kafka_mock),
        ):
            svc = KnowledgeSourceService(
                session=db_session,
                validator=_ok_validator(),
            )
            response = await svc.create(_VALID_PAYLOAD)

        kafka_mock.send_and_wait.assert_awaited_once()
        call_args = kafka_mock.send_and_wait.call_args
        topic = call_args.args[0]
        assert topic == "knowledge.source.created"

        import json
        payload = json.loads(call_args.kwargs["value"].decode())
        assert payload["event_type"] == "knowledge_source_created"
        assert payload["source_id"] == str(response.id)
        assert payload["connector_type"] == "github"

    @pytest.mark.asyncio
    async def test_record_persisted_even_if_kafka_fails(
        self, db_session: AsyncSession
    ) -> None:
        """DB commit happens before Kafka; record survives Kafka failure."""
        kafka_mock = _mock_kafka_producer()
        kafka_mock.send_and_wait = AsyncMock(side_effect=RuntimeError("Kafka down"))

        with patch(
            "src.events.producer.get_kafka_producer",
            new=AsyncMock(return_value=kafka_mock),
        ):
            svc = KnowledgeSourceService(
                session=db_session,
                validator=_ok_validator(),
            )
            with pytest.raises(RuntimeError, match="Kafka down"):
                await svc.create(_VALID_PAYLOAD)

        from sqlalchemy import select
        result = await db_session.execute(select(KnowledgeSourceRecord))
        records = result.scalars().all()
        assert len(records) == 1
        assert records[0].scope == "acme-org/api-service"


# ---------------------------------------------------------------------------
# AC-5: list_all() ordered by created_at DESC
# ---------------------------------------------------------------------------


class TestListAll:
    @pytest.mark.asyncio
    async def test_list_all_returns_desc_order(
        self, db_session: AsyncSession
    ) -> None:
        await _insert_source(db_session, scope="scope-first", created_offset=0)
        await _insert_source(db_session, scope="scope-second", created_offset=1)
        await _insert_source(db_session, scope="scope-third", created_offset=2)

        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())
        results = await svc.list_all()

        assert len(results) == 3
        assert results[0].scope == "scope-third"
        assert results[1].scope == "scope-second"
        assert results[2].scope == "scope-first"

    @pytest.mark.asyncio
    async def test_list_all_empty(self, db_session: AsyncSession) -> None:
        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())
        results = await svc.list_all()
        assert results == []


# ---------------------------------------------------------------------------
# AC-6: toggle_active sets is_active and status
# ---------------------------------------------------------------------------


class TestToggleActive:
    @pytest.mark.asyncio
    async def test_deactivate_sets_inactive(self, db_session: AsyncSession) -> None:
        record = await _insert_source(db_session)
        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())

        response = await svc.toggle_active(record.id, is_active=False)

        assert response.is_active is False
        assert response.status == SourceStatus.INACTIVE

    @pytest.mark.asyncio
    async def test_reactivate_sets_active(self, db_session: AsyncSession) -> None:
        record = await _insert_source(db_session)
        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())

        # Deactivate first
        await svc.toggle_active(record.id, is_active=False)
        # Re-activate
        response = await svc.toggle_active(record.id, is_active=True)

        assert response.is_active is True
        assert response.status == SourceStatus.ACTIVE

    # AC-7: HTTP 404 for unknown id
    @pytest.mark.asyncio
    async def test_toggle_unknown_id_raises_404(
        self, db_session: AsyncSession
    ) -> None:
        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())

        with pytest.raises(HTTPException) as exc_info:
            await svc.toggle_active(uuid4(), is_active=False)

        assert exc_info.value.status_code == 404


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_record(self, db_session: AsyncSession) -> None:
        record = await _insert_source(db_session)
        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())

        await svc.delete(record.id)

        from sqlalchemy import select
        result = await db_session.execute(
            select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.id == record.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_unknown_id_raises_404(
        self, db_session: AsyncSession
    ) -> None:
        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())

        with pytest.raises(HTTPException) as exc_info:
            await svc.delete(uuid4())

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_does_not_affect_other_records(
        self, db_session: AsyncSession
    ) -> None:
        keep = await _insert_source(db_session, scope="keep-me")
        remove = await _insert_source(db_session, scope="remove-me")
        svc = KnowledgeSourceService(session=db_session, validator=_ok_validator())

        await svc.delete(remove.id)

        remaining = await svc.list_all()
        assert [r.id for r in remaining] == [keep.id]
