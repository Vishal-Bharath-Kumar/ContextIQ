"""Tests for health-check route and connector audit trail — TASK-US039-04.

Covers acceptance criteria:
  AC-3  POST /health-check returns HealthCheckResponse ok=true on success
  AC-3  POST /health-check returns ok=false (HTTP 200) on connector error
  AC-5  Audit row inserted after POST (created), PATCH /status, POST /health-check
  AC-4  PATCH /status changes take effect immediately (backend)
        (existing toggle test extended with audit verification)
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.connector_sdk.schemas.health import HealthStatus
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
from src.knowledge_sources.services.health_check_service import HealthCheckService
from src.main import app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN, sub="admin-sub-001")
_NOW = dt.datetime(2026, 7, 18, 12, 0, 0, tzinfo=dt.UTC)
_SOURCE_ID = uuid4()

_SAMPLE_RESPONSE = KnowledgeSourceResponse(
    id=_SOURCE_ID,
    name="Acme GitHub",
    connector_type=ConnectorType.GITHUB,
    credentials_vault_path="secret/contextiq/github/acme",
    scope="acme-org/api-service",
    sync_schedule="0 */6 * * *",
    token_budget_weight=1.0,
    status=SourceStatus.ACTIVE,
    is_active=True,
    last_sync_at=_NOW,
    document_count=5,
    created_at=_NOW,
    updated_at=_NOW,
)

_VALID_PAYLOAD = {
    "name": "Acme GitHub",
    "connector_type": "github",
    "credentials_vault_path": "secret/contextiq/github/acme",
    "scope": "acme-org/api-service",
    "sync_schedule": "0 */6 * * *",
    "token_budget_weight": 1.0,
}


def _null_audit_repo() -> AuditRepository:
    """Return an AuditRepository whose log() call is a no-op."""
    repo = AsyncMock(spec=AuditRepository)
    return repo


async def _mock_db_session() -> AsyncMock:  # type: ignore[misc]
    """Yield a mock AsyncSession so route handlers with Depends(get_db) don't need a real DB."""
    session = AsyncMock()
    session.commit = AsyncMock()
    yield session


# ---------------------------------------------------------------------------
# HealthCheckService unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_service_success() -> None:
    """AC-3: Service returns ok=True when connector.health_check() succeeds."""
    record = MagicMock()
    record.connector_type = "github"
    record.credentials_vault_path = "secret/contextiq/github/acme"
    record.scope = "acme-org/repo"

    repo_mock = AsyncMock()
    repo_mock.get_by_id.return_value = record

    connector_mock = AsyncMock()
    connector_mock.authenticate = AsyncMock(return_value=None)
    connector_mock.health_check = AsyncMock(
        return_value=HealthStatus(healthy=True, message="ok", checked_at=_NOW)
    )
    connector_cls = MagicMock(return_value=connector_mock)
    config_cls = MagicMock()

    session_mock = AsyncMock()

    with patch(
        "src.knowledge_sources.services.health_check_service.KnowledgeSourceRepository",
        return_value=repo_mock,
    ), patch(
        "src.knowledge_sources.services.health_check_service.CONNECTOR_CLASS_MAP",
        {"github": (connector_cls, config_cls)},
    ):
        svc = HealthCheckService(session_mock)
        result = await svc.run(_SOURCE_ID)

    assert result.ok is True
    assert result.latency_ms >= 0
    assert result.detail is None


@pytest.mark.asyncio
async def test_health_check_service_connector_error() -> None:
    """AC-3: Service returns ok=False (HTTP 200) when connector raises."""
    record = MagicMock()
    record.connector_type = "github"
    record.credentials_vault_path = "secret/contextiq/github/acme"
    record.scope = "acme-org/repo"

    repo_mock = AsyncMock()
    repo_mock.get_by_id.return_value = record

    connector_mock = AsyncMock()
    connector_mock.authenticate = AsyncMock(side_effect=ConnectionError("timeout"))
    connector_cls = MagicMock(return_value=connector_mock)
    config_cls = MagicMock()

    session_mock = AsyncMock()

    with patch(
        "src.knowledge_sources.services.health_check_service.KnowledgeSourceRepository",
        return_value=repo_mock,
    ), patch(
        "src.knowledge_sources.services.health_check_service.CONNECTOR_CLASS_MAP",
        {"github": (connector_cls, config_cls)},
    ):
        svc = HealthCheckService(session_mock)
        result = await svc.run(_SOURCE_ID)

    assert result.ok is False
    assert result.latency_ms >= 0
    assert "timeout" in (result.detail or "")


@pytest.mark.asyncio
async def test_health_check_service_source_not_found() -> None:
    """AC-3: Service raises HTTP 404 when source_id does not exist."""
    repo_mock = AsyncMock()
    repo_mock.get_by_id.return_value = None

    session_mock = AsyncMock()

    with patch(
        "src.knowledge_sources.services.health_check_service.KnowledgeSourceRepository",
        return_value=repo_mock,
    ):
        svc = HealthCheckService(session_mock)
        with pytest.raises(HTTPException) as exc_info:
            await svc.run(uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_health_check_service_unimplemented_connector() -> None:
    """AC-3: Service raises HTTP 501 when connector type has no implementation."""
    record = MagicMock()
    record.connector_type = "nonexistent"
    record.credentials_vault_path = "secret/x"
    record.scope = "scope"

    repo_mock = AsyncMock()
    repo_mock.get_by_id.return_value = record

    session_mock = AsyncMock()

    with patch(
        "src.knowledge_sources.services.health_check_service.KnowledgeSourceRepository",
        return_value=repo_mock,
    ):
        svc = HealthCheckService(session_mock)
        with pytest.raises(HTTPException) as exc_info:
            await svc.run(_SOURCE_ID)

    assert exc_info.value.status_code == 501


# ---------------------------------------------------------------------------
# AuditRepository unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_repository_log_adds_record() -> None:
    """AC-5: AuditRepository.log() adds a ConnectorAuditLog record and flushes."""
    session_mock = AsyncMock()
    session_mock.add = MagicMock()
    session_mock.flush = AsyncMock()

    repo = AuditRepository(session_mock)
    entry = AuditEntry(
        connector_id=_SOURCE_ID,
        event_type=AuditEventType.HEALTH_CHECKED,
        actor_user_id="admin-sub-001",
        detail="ok=True latency_ms=12",
    )
    await repo.log(entry)

    session_mock.add.assert_called_once()
    session_mock.flush.assert_awaited_once()
    added_record = session_mock.add.call_args[0][0]
    assert str(added_record.connector_id) == str(_SOURCE_ID)
    assert added_record.event_type == AuditEventType.HEALTH_CHECKED
    assert added_record.actor_user_id == "admin-sub-001"


# ---------------------------------------------------------------------------
# Router integration tests (mocked deps, no DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_route_success() -> None:
    """AC-3: POST /health-check returns 200 with ok=true when connector is healthy."""
    hc_response = HealthCheckResponse(ok=True, latency_ms=25)
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
                response = await client.post(
                    f"/v1/knowledge-sources/{_SOURCE_ID}/health-check"
                )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["latency_ms"] == 25
        audit_mock.log.assert_awaited_once()
        logged_entry: AuditEntry = audit_mock.log.call_args[0][0]
        assert logged_entry.event_type == AuditEventType.HEALTH_CHECKED
        assert logged_entry.actor_user_id == "admin-sub-001"
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_health_check_route_connector_failure_returns_200() -> None:
    """AC-3: POST /health-check returns HTTP 200 with ok=false on connector error."""
    hc_response = HealthCheckResponse(ok=False, latency_ms=8, detail="connection refused")
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
                response = await client.post(
                    f"/v1/knowledge-sources/{_SOURCE_ID}/health-check"
                )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["detail"] == "connection refused"
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_create_route_emits_audit_entry() -> None:
    """AC-5: POST /knowledge-sources inserts a 'created' audit entry."""
    svc_mock = AsyncMock()
    svc_mock.create.return_value = _SAMPLE_RESPONSE
    audit_mock = AsyncMock(spec=AuditRepository)

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc_mock
    app.dependency_overrides[get_audit_repo] = lambda: audit_mock
    app.dependency_overrides[get_db] = _mock_db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/knowledge-sources", json=_VALID_PAYLOAD)

        assert response.status_code == 201
        audit_mock.log.assert_awaited_once()
        entry: AuditEntry = audit_mock.log.call_args[0][0]
        assert entry.event_type == AuditEventType.CREATED
        assert entry.actor_user_id == "admin-sub-001"
        assert str(entry.connector_id) == str(_SOURCE_ID)
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_toggle_status_route_emits_audit_entry() -> None:
    """AC-5: PATCH /{id}/status inserts a 'status_changed' audit entry."""
    inactive_response = _SAMPLE_RESPONSE.model_copy(
        update={"status": SourceStatus.INACTIVE, "is_active": False}
    )
    svc_mock = AsyncMock()
    svc_mock.toggle_active.return_value = inactive_response
    audit_mock = AsyncMock(spec=AuditRepository)

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc_mock
    app.dependency_overrides[get_audit_repo] = lambda: audit_mock
    app.dependency_overrides[get_db] = _mock_db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/v1/knowledge-sources/{_SOURCE_ID}/status",
                json={"active": False},
            )

        assert response.status_code == 200
        audit_mock.log.assert_awaited_once()
        entry: AuditEntry = audit_mock.log.call_args[0][0]
        assert entry.event_type == AuditEventType.STATUS_CHANGED
        assert entry.actor_user_id == "admin-sub-001"
        assert "inactive" in (entry.detail or "")
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)
