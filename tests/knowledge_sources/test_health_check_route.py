"""Route-level integration tests for POST /health-check — TASK-US039-05.

Covers acceptance criteria:
  AC-3  POST /health-check returns ok=True with latency_ms on success
  AC-3  POST /health-check returns ok=False (HTTP 200) on connector error
  AC-3  POST /health-check returns HTTP 404 when source does not exist
  AC-3  POST /health-check returns HTTP 403 for non-admin callers

All tests use mocked dependencies — no real database or Vault connections.
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
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
from src.main import app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN, sub="admin-sub-001")
_DEVELOPER_CLAIMS = make_test_claims(PlatformRole.DEVELOPER, sub="dev-sub-002")
_SOURCE_ID = uuid4()


async def _mock_db_session() -> AsyncMock:  # type: ignore[misc]
    session = AsyncMock()
    session.commit = AsyncMock()
    yield session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_returns_ok() -> None:
    """AC-3: successful health_check() returns ok=True with latency_ms."""
    hc_response = HealthCheckResponse(ok=True, latency_ms=42, detail=None)
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
        assert r.json()["ok"] is True
        assert r.json()["latency_ms"] == 42
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_health_check_returns_ok_false_on_connector_error() -> None:
    """AC-3: connector exception returns ok=False with detail — not a 5xx."""
    hc_response = HealthCheckResponse(
        ok=False, latency_ms=10, detail="Connection refused"
    )
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
        assert r.json()["ok"] is False
        assert "Connection refused" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_health_check_returns_404_for_unknown_source() -> None:
    """AC-3: health_check raises HTTP 404 when source_id does not exist."""
    audit_mock = AsyncMock(spec=AuditRepository)

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_audit_repo] = lambda: audit_mock
    app.dependency_overrides[get_db] = _mock_db_session

    try:
        with patch(
            "src.knowledge_sources.routers.knowledge_source_router.HealthCheckService"
        ) as MockHCS:
            instance = AsyncMock()
            instance.run = AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not found")
            )
            MockHCS.return_value = instance

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                r = await client.post(
                    f"/v1/knowledge-sources/{uuid4()}/health-check"
                )

        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_audit_repo, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_health_check_returns_403_for_non_admin() -> None:
    """AC-3: non-admin callers receive HTTP 403."""
    app.dependency_overrides[decode_jwt_claims] = lambda: _DEVELOPER_CLAIMS
    app.dependency_overrides[get_db] = _mock_db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/v1/knowledge-sources/{_SOURCE_ID}/health-check"
            )

        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_db, None)
