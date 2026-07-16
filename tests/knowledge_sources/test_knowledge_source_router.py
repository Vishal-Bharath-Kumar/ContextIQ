"""Tests for Knowledge Source Admin API routes — TASK-US025-04.

Uses httpx.AsyncClient with a mocked KnowledgeSourceService so no database
or Vault connections are required.

Acceptance criteria covered:
  AC-1  POST with valid payload returns HTTP 201 and KnowledgeSourceResponse
  AC-2  POST with invalid Vault path returns HTTP 400 with descriptive detail
  AC-3  POST with duplicate (connector_type, scope) returns HTTP 409
  AC-4  GET returns JSON array with status, last_sync_at, document_count
  AC-5  PATCH /{id}/status with {"active": false} sets status="inactive"
  AC-6  PATCH /{unknown}/status returns HTTP 404
  AC-7  Non-admin requests return HTTP 403
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.knowledge_sources.dependencies import get_knowledge_source_service
from src.knowledge_sources.schemas.knowledge_source import (
    ConnectorType,
    KnowledgeSourceResponse,
    SourceStatus,
)
from src.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN)
_DEVELOPER_CLAIMS = make_test_claims(PlatformRole.DEVELOPER)

_NOW = dt.datetime(2026, 7, 16, 12, 0, 0, tzinfo=dt.UTC)

_SOURCE_ID = uuid4()

_SAMPLE_RESPONSE = KnowledgeSourceResponse(
    id=_SOURCE_ID,
    connector_type=ConnectorType.GITHUB,
    credentials_vault_path="secret/contextiq/github/acme",
    scope="acme-org/api-service",
    sync_schedule="0 */6 * * *",
    token_budget_weight=1.0,
    status=SourceStatus.ACTIVE,
    is_active=True,
    last_sync_at=_NOW,
    document_count=42,
    created_at=_NOW,
    updated_at=_NOW,
)

_VALID_PAYLOAD = {
    "connector_type": "github",
    "credentials_vault_path": "secret/contextiq/github/acme",
    "scope": "acme-org/api-service",
    "sync_schedule": "0 */6 * * *",
    "token_budget_weight": 1.0,
}


def _mock_service(**kwargs: object) -> AsyncMock:
    """Return an AsyncMock configured with the given method return values."""
    svc = AsyncMock()
    for method, value in kwargs.items():
        if isinstance(value, Exception):
            getattr(svc, method).side_effect = value
        else:
            getattr(svc, method).return_value = value
    return svc


# ---------------------------------------------------------------------------
# AC-1: POST success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_knowledge_source_returns_201() -> None:
    """AC-1: POST with valid payload returns HTTP 201 and KnowledgeSourceResponse."""
    svc = _mock_service(create=_SAMPLE_RESPONSE)
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/knowledge-sources", json=_VALID_PAYLOAD)
        assert response.status_code == 201
        body = response.json()
        assert body["id"] == str(_SOURCE_ID)
        assert body["connector_type"] == "github"
        assert body["status"] == "active"
        assert body["document_count"] == 42
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)


# ---------------------------------------------------------------------------
# AC-2: POST with invalid Vault path returns 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_knowledge_source_invalid_vault_path_returns_400() -> None:
    """AC-2: POST with invalid Vault path returns HTTP 400 with descriptive detail."""
    svc = _mock_service(
        create=HTTPException(status_code=400, detail="Vault path 'bad/path' not found")
    )
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/knowledge-sources", json=_VALID_PAYLOAD)
        assert response.status_code == 400
        assert "Vault path" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)


# ---------------------------------------------------------------------------
# AC-3: POST with duplicate returns 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_knowledge_source_duplicate_returns_409() -> None:
    """AC-3: POST with duplicate (connector_type, scope) returns HTTP 409."""
    svc = _mock_service(
        create=HTTPException(
            status_code=409,
            detail="A knowledge source for connector 'github' with scope 'acme-org/api-service' is already registered.",
        )
    )
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/knowledge-sources", json=_VALID_PAYLOAD)
        assert response.status_code == 409
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)


# ---------------------------------------------------------------------------
# AC-4: GET returns list with status, last_sync_at, document_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_knowledge_sources_returns_200_with_fields() -> None:
    """AC-4: GET returns JSON array including status, last_sync_at, document_count."""
    svc = _mock_service(list_all=[_SAMPLE_RESPONSE])
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/knowledge-sources")
        assert response.status_code == 200
        items = response.json()
        assert isinstance(items, list)
        assert len(items) == 1
        item = items[0]
        assert "status" in item
        assert "last_sync_at" in item
        assert "document_count" in item
        assert item["document_count"] == 42
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)


# ---------------------------------------------------------------------------
# AC-5: PATCH sets status=inactive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_status_inactive_returns_200() -> None:
    """AC-5: PATCH /{id}/status with {"active": false} sets status="inactive"."""
    inactive_response = _SAMPLE_RESPONSE.model_copy(
        update={"status": SourceStatus.INACTIVE, "is_active": False}
    )
    svc = _mock_service(toggle_active=inactive_response)
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/v1/knowledge-sources/{_SOURCE_ID}/status",
                json={"active": False},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "inactive"
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)


# ---------------------------------------------------------------------------
# AC-6: PATCH unknown id returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_status_unknown_id_returns_404() -> None:
    """AC-6: PATCH /{unknown}/status returns HTTP 404."""
    unknown_id = uuid4()
    svc = _mock_service(
        toggle_active=HTTPException(
            status_code=404,
            detail=f"Knowledge source {unknown_id} not found",
        )
    )
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/v1/knowledge-sources/{unknown_id}/status",
                json={"active": True},
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)


# ---------------------------------------------------------------------------
# AC-7: Non-admin requests return 403
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/v1/knowledge-sources", _VALID_PAYLOAD),
        ("GET", "/v1/knowledge-sources", None),
        ("PATCH", f"/v1/knowledge-sources/{_SOURCE_ID}/status", {"active": False}),
    ],
)
@pytest.mark.asyncio
async def test_non_admin_returns_403(
    method: str, path: str, body: dict | None
) -> None:
    """AC-7: Non-admin requests to all three endpoints return HTTP 403."""
    app.dependency_overrides[decode_jwt_claims] = lambda: _DEVELOPER_CLAIMS
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            if method == "POST":
                response = await client.post(path, json=body)
            elif method == "GET":
                response = await client.get(path)
            else:
                response = await client.patch(path, json=body)
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
