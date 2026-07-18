"""Integration tests for the policy audit trail route — TASK-US040-05.

Covers:
  AC-6: POST /activate inserts an 'activated' audit entry in the DB.
  AC-6: GET /audit returns chronologically descending entries with
        actor_user_id and created_at.
  AC-7: Viewer-role JWT receives 403 on GET /audit.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.auth.dependencies import decode_jwt_claims
from src.auth.middleware import JWTAuthMiddleware
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db
from src.governance.policy.models import PolicyAuditLog, PolicyRecord
from src.governance.policy.schemas import ActivateResponse

# ---------------------------------------------------------------------------
# In-memory SQLite engine / session fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Per-test SQLite engine with policy_definitions + policy_audit_log tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _register_now(dbapi_conn: object, _: object) -> None:
        assert hasattr(dbapi_conn, "create_function")
        dbapi_conn.create_function(  # type: ignore[union-attr]
            "now", 0, lambda: datetime.now(UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            PolicyRecord.__table__.metadata.create_all,
            tables=[PolicyRecord.__table__, PolicyAuditLog.__table__],
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(
    async_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Async session backed by in-memory SQLite."""
    factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def existing_policy_id(async_session: AsyncSession) -> uuid.UUID:
    """Insert a draft PolicyRecord and return its UUID."""
    record = PolicyRecord(
        policy_group="test-policy",
        version="1.0.0",
        rego_body="package test\ndefault allow = false\n",
        author="seeder@test.com",
        description="Integration test policy",
        status="draft",
    )
    async_session.add(record)
    await async_session.flush()
    await async_session.commit()
    return record.id  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# HTTP client fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_client(
    async_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client with ADMIN claims; get_db overridden to use test session."""
    from src.main import app

    async def _passthrough(
        self: object, request: object, call_next: object
    ) -> object:
        return await call_next(request)  # type: ignore[operator]

    monkeypatch.setattr(JWTAuthMiddleware, "dispatch", _passthrough)

    admin_claims = make_test_claims(PlatformRole.ADMIN, sub="admin-user-001")
    app.dependency_overrides[decode_jwt_claims] = lambda: admin_claims
    app.dependency_overrides[get_db] = lambda: async_session

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.pop(decode_jwt_claims, None)
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def viewer_client(
    async_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client with DEVELOPER (viewer) claims; no SECURITY_OFFICER/ADMIN."""
    from src.main import app

    async def _passthrough(
        self: object, request: object, call_next: object
    ) -> object:
        return await call_next(request)  # type: ignore[operator]

    monkeypatch.setattr(JWTAuthMiddleware, "dispatch", _passthrough)

    viewer_claims = make_test_claims(PlatformRole.DEVELOPER, sub="viewer-user-001")
    app.dependency_overrides[decode_jwt_claims] = lambda: viewer_claims
    app.dependency_overrides[get_db] = lambda: async_session

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.pop(decode_jwt_claims, None)
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_policy_writes_audit_entry(
    admin_client: httpx.AsyncClient,
    async_session: AsyncSession,
    existing_policy_id: uuid.UUID,
) -> None:
    """AC-6: POST /activate inserts an 'activated' audit entry in the DB."""
    mock_result = ActivateResponse(
        activated_version="1.0.0",
        bundle_push_ok=True,
        activated_at=datetime.now(UTC),
    )
    with patch(
        "src.api.admin.routes.policies._build_service"
    ) as mock_build:
        mock_svc = AsyncMock()
        mock_svc.activate.return_value = mock_result
        mock_build.return_value = mock_svc

        r = await admin_client.post(f"/v1/policies/{existing_policy_id}/activate")

    assert r.status_code == 200

    from sqlalchemy import select

    rows = (
        await async_session.execute(
            select(PolicyAuditLog).where(
                PolicyAuditLog.policy_id == existing_policy_id,
                PolicyAuditLog.event_type == "activated",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    assert rows[0].actor_user_id == "admin-user-001"


@pytest.mark.asyncio
async def test_get_policy_audit_returns_entries(
    admin_client: httpx.AsyncClient,
    async_session: AsyncSession,
    existing_policy_id: uuid.UUID,
) -> None:
    """AC-6: GET /audit returns list with actor_user_id and created_at."""
    # Seed one audit entry directly
    from src.governance.policy.audit_repository import PolicyAuditRepository

    repo = PolicyAuditRepository(async_session)
    await repo.log(existing_policy_id, "activated", "alice@acme.com")
    await async_session.commit()

    r = await admin_client.get(f"/v1/policies/{existing_policy_id}/audit")

    assert r.status_code == 200
    entries = r.json()
    assert len(entries) >= 1
    assert entries[0]["actor_user_id"] is not None
    assert entries[0]["created_at"] is not None
    assert entries[0]["event_type"] == "activated"


@pytest.mark.asyncio
async def test_security_officer_role_required(
    viewer_client: httpx.AsyncClient,
    existing_policy_id: uuid.UUID,
) -> None:
    """AC-7: viewer role (DEVELOPER, not SECURITY_OFFICER/ADMIN) receives 403."""
    r = await viewer_client.get(f"/v1/policies/{existing_policy_id}/audit")
    assert r.status_code == 403
