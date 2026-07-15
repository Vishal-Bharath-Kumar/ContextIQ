"""
Shared pytest fixtures for tests/audit/.

Provides:
  - ``bypass_jwt_middleware`` — autouse, patches JWTAuthMiddleware for all
    audit tests so requests reach routes without a real Bearer token.
  - ``async_engine`` / ``db_session`` — per-test in-memory SQLite engine +
    session; also overrides FastAPI's get_db / get_read_db dependencies so
    route handlers write to the same in-memory DB the test queries directly.
  - Seed fixtures: ``seed_mixed_audit_rows``, ``seed_60_audit_rows``,
    ``seed_audit_rows_yesterday``, ``seed_model``, ``mock_policy_create``.
  - ``auditor_auth_header`` — injects AUDITOR claims via dependency override,
    returns an Authorization header dict for use with AsyncClient.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.audit.admin_audit_log.hash_chain import (
    GENESIS_PREV_HASH,
    compute_row_hash,
    row_fields_for_hashing,
)
from src.audit.admin_audit_log.models import AdminAuditLog
from src.auth.dependencies import decode_jwt_claims
from src.auth.middleware import JWTAuthMiddleware
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db, get_read_db
from src.data.models.base import Base
from src.main import app


# ---------------------------------------------------------------------------
# JWT middleware bypass (autouse — replaces real signature verification so
# tests can inject claims via app.dependency_overrides without a signed JWT)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def bypass_jwt_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Replace JWTAuthMiddleware.dispatch with a pass-through for all audit tests.

    RBAC enforcement is still exercised through the require_auditor FastAPI
    dependency (which reads claims from app.dependency_overrides), so AC-5
    tests remain meaningful even with middleware bypassed.
    """
    from starlette.requests import Request
    from starlette.responses import Response

    async def _passthrough(self: Any, request: Request, call_next: Any) -> Response:
        return await call_next(request)

    monkeypatch.setattr(JWTAuthMiddleware, "dispatch", _passthrough)


# ---------------------------------------------------------------------------
# Per-test in-memory SQLite engine + session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_engine():
    """
    Per-test in-memory SQLite engine.

    Creates all ORM tables before the test; disposes the engine after.
    PostgreSQL-specific column types (JSONB) fall back gracefully on SQLite.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Async SQLAlchemy session backed by the per-test in-memory SQLite engine.

    Overrides get_db and get_read_db so that FastAPI route handlers
    (including AuditContext) write to the same in-memory DB that the test
    queries directly via this session object.
    """
    async_session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as session:

        async def _get_test_session() -> AsyncGenerator[AsyncSession, None]:
            yield session

        app.dependency_overrides[get_db] = _get_test_session
        app.dependency_overrides[get_read_db] = _get_test_session

        yield session

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_read_db, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audit_row(
    *,
    action: str = "policy.created",
    resource_type: str = "policy",
    resource_id: str = "pol-001",
    actor_user_id: str = "user-001",
    ip_address: str = "10.0.0.1",
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    prev_hash: str = GENESIS_PREV_HASH,
) -> AdminAuditLog:
    ts = timestamp or datetime.now(timezone.utc)
    fields = row_fields_for_hashing(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        before_state=before_state,
        after_state=after_state,
        timestamp=ts,
    )
    row = AdminAuditLog(
        id=uuid.uuid4(),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        before_state=before_state,
        after_state=after_state,
        timestamp=ts,
        row_hash=compute_row_hash(prev_hash, fields),
    )
    return row


# ---------------------------------------------------------------------------
# Seed fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seed_mixed_audit_rows(db_session: AsyncSession) -> list[AdminAuditLog]:
    """
    Insert audit rows with varied actions and actors so AC-4 filter tests
    can verify that each filter predicate works in isolation.
    """
    rows: list[AdminAuditLog] = []
    prev = GENESIS_PREV_HASH
    base_ts = datetime(2026, 7, 9, 10, 0, 0, tzinfo=timezone.utc)

    for i, (action, user) in enumerate([
        ("policy.created",   "user-001"),
        ("policy.activated", "user-002"),
        ("policy.created",   "user-001"),
        ("model.registered", "user-003"),
        ("model.status_changed", "user-002"),
    ]):
        row = _make_audit_row(
            action=action,
            resource_type=action.split(".")[0],
            actor_user_id=user,
            timestamp=base_ts + timedelta(seconds=i),
            prev_hash=prev,
        )
        db_session.add(row)
        prev = row.row_hash
        rows.append(row)

    await db_session.flush()
    return rows


@pytest_asyncio.fixture
async def seed_60_audit_rows(db_session: AsyncSession) -> list[AdminAuditLog]:
    """Insert 60 rows so pagination cursor tests can verify page 1 ≠ page 2."""
    rows: list[AdminAuditLog] = []
    prev = GENESIS_PREV_HASH
    base_ts = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(60):
        row = _make_audit_row(
            action="policy.created",
            timestamp=base_ts + timedelta(seconds=i),
            prev_hash=prev,
        )
        db_session.add(row)
        prev = row.row_hash
        rows.append(row)

    await db_session.flush()
    return rows


@pytest_asyncio.fixture
async def seed_audit_rows_yesterday(db_session: AsyncSession) -> list[AdminAuditLog]:
    """
    Insert 3 rows with timestamps on 2026-07-09 for archive service tests.

    The archive test hardcodes ``day=date(2026, 7, 9)`` so these rows must
    fall within that calendar day (UTC).
    """
    rows: list[AdminAuditLog] = []
    prev = GENESIS_PREV_HASH
    target_day = date(2026, 7, 9)
    base_ts = datetime(target_day.year, target_day.month, target_day.day, 8, 0, 0, tzinfo=timezone.utc)

    for i in range(3):
        row = _make_audit_row(
            action="policy.created",
            timestamp=base_ts + timedelta(hours=i),
            prev_hash=prev,
        )
        db_session.add(row)
        prev = row.row_hash
        rows.append(row)

    await db_session.flush()
    return rows


@pytest.fixture
def seed_model() -> SimpleNamespace:
    """
    Return a minimal model-like object with a UUID id.

    The model status route uses the id from the URL path only — it does not
    query the model from the DB in the current placeholder implementation.
    """
    return SimpleNamespace(id=uuid.uuid4())


@pytest.fixture
def mock_policy_create(db_session: AsyncSession) -> None:
    """
    Ensures the test DB is ready for POST /v1/policies.

    No extra mocking is required — the create_policy route is self-contained
    (it generates its own resource_id and logs the audit row).
    """
    return None


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auditor_auth_header() -> dict[str, str]:
    """
    Override decode_jwt_claims with AUDITOR claims and return a header dict.

    The Authorization value is a placeholder — the actual token is never
    verified because bypass_jwt_middleware is active for all audit tests.
    RBAC is still enforced by the require_auditor FastAPI dependency which
    reads the overridden claims.
    """
    claims = make_test_claims(PlatformRole.AUDITOR)
    app.dependency_overrides[decode_jwt_claims] = lambda: claims
    yield {"Authorization": "Bearer test-auditor-token"}
    app.dependency_overrides.pop(decode_jwt_claims, None)
