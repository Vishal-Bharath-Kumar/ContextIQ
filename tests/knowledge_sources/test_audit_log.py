"""Audit trail integration tests for knowledge-source mutations — TASK-US039-05.

Covers acceptance criteria:
  AC-5  POST /v1/knowledge-sources inserts an audit entry with event_type='created'
  AC-5  PATCH /v1/knowledge-sources/{id}/status inserts event_type='status_changed'
  AC-5  POST /v1/knowledge-sources/{id}/health-check inserts event_type='health_checked'

All tests use mocked service/repository dependencies — no real DB required.
The AuditRepository mock verifies that .log() is called with the expected AuditEntry.
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, call, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db
from src.knowledge_sources.dependencies import get_knowledge_source_service
from src.knowledge_sources.repositories.audit_repository import AuditRepository
from src.knowledge_sources.routers.knowledge_source_router import get_audit_repo
from src.knowledge_sources.schemas.connector_audit import (
    AuditEntry,
    AuditEventType,
    HealthCheckResponse,
)
from src.knowledge_sources.schemas.knowledge_source import (
    ConnectorType,
    KnowledgeSourceResponse,
    SourceStatus,
)
from src.main import app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN, sub="admin-sub-001")
_NOW = dt.datetime(2026, 7, 18, 12, 0, 0, tzinfo=dt.UTC)
_SOURCE_ID = uuid4()

_SAMPLE_RESPONSE = KnowledgeSourceResponse(
    id=_SOURCE_ID,
    connector_type=ConnectorType.GITHUB,
    credentials_vault_path="secret/contextiq/github/test",
    scope="my-org/my-repo",
    sync_schedule="0 2 * * *",
    token_budget_weight=1.0,
    status=SourceStatus.ACTIVE,
    is_active=True,
    last_sync_at=_NOW,
    document_count=0,
    created_at=_NOW,
    updated_at=_NOW,
)

_VALID_PAYLOAD = {
    "connector_type": "github",
    "credentials_vault_path": "secret/contextiq/github/test",
    "scope": "my-org/my-repo",
    "sync_schedule": "0 2 * * *",
    "token_budget_weight": 1.0,
}


async def _mock_db_session() -> AsyncMock:  # type: ignore[misc]
    session = AsyncMock()
    session.commit = AsyncMock()
    yield session


# ---------------------------------------------------------------------------
# AC-5: 'created' audit entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_connector_writes_audit_entry() -> None:
    """AC-5: POST /v1/knowledge-sources logs an audit entry with event_type='created'."""
    svc_mock = AsyncMock()
    svc_mock.create = AsyncMock(return_value=_SAMPLE_RESPONSE)
    audit_mock = AsyncMock(spec=AuditRepository)

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc_mock
    app.dependency_overrides[get_audit_repo] = lambda: audit_mock
    app.dependency_overrides[get_db] = _mock_db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            r = await client.post("/v1/knowledge-sources", json=_VALID_PAYLOAD)

        assert r.status_code == 201
        audit_mock.log.assert_awaited_once()
        logged: AuditEntry = audit_mock.log.call_args[0][0]
        assert logged.event_type == AuditEventType.CREATED
        assert str(logged.connector_id) == str(_SOURCE_ID)
        assert logged.actor_user_id == "admin-sub-001"
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-5: 'status_changed' audit entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_change_writes_audit_entry() -> None:
    """AC-5: PATCH /status logs an audit entry with event_type='status_changed'."""
    inactive_response = _SAMPLE_RESPONSE.model_copy(
        update={"status": SourceStatus.INACTIVE, "is_active": False}
    )
    svc_mock = AsyncMock()
    svc_mock.toggle_active = AsyncMock(return_value=inactive_response)
    audit_mock = AsyncMock(spec=AuditRepository)

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc_mock
    app.dependency_overrides[get_audit_repo] = lambda: audit_mock
    app.dependency_overrides[get_db] = _mock_db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            r = await client.patch(
                f"/v1/knowledge-sources/{_SOURCE_ID}/status",
                json={"active": False},
            )

        assert r.status_code == 200
        audit_mock.log.assert_awaited_once()
        logged: AuditEntry = audit_mock.log.call_args[0][0]
        assert logged.event_type == AuditEventType.STATUS_CHANGED
        assert str(logged.connector_id) == str(_SOURCE_ID)
        assert "inactive" in (logged.detail or "")
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-5: 'health_checked' audit entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_writes_audit_entry() -> None:
    """AC-5: POST /health-check logs an audit entry with event_type='health_checked'."""
    hc_response = HealthCheckResponse(ok=True, latency_ms=5, detail=None)
    audit_mock = AsyncMock(spec=AuditRepository)

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_audit_repo] = lambda: audit_mock
    app.dependency_overrides[get_db] = _mock_db_session

    try:
        with patch(
            "src.knowledge_sources.routers.knowledge_source_router.HealthCheckService"
        ) as MockHCS:
            instance = AsyncMock()
            instance.run = AsyncMock(return_value=hc_response)
            MockHCS.return_value = instance

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                r = await client.post(
                    f"/v1/knowledge-sources/{_SOURCE_ID}/health-check"
                )

        assert r.status_code == 200
        audit_mock.log.assert_awaited_once()
        logged: AuditEntry = audit_mock.log.call_args[0][0]
        assert logged.event_type == AuditEventType.HEALTH_CHECKED
        assert str(logged.connector_id) == str(_SOURCE_ID)
        assert logged.actor_user_id == "admin-sub-001"
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)
