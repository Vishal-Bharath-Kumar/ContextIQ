"""Tests for the Model Registry API routes — TASK-US018-04.

Uses httpx.AsyncClient with mocked service layer and audit context so no
database, Redis, or Kafka connections are required.

Acceptance criteria covered:
  AC-1  POST with a valid payload returns HTTP 201 and a ModelDefinition body
  AC-2  POST with a duplicate model_id returns HTTP 409 with an error message
  AC-3  POST with an invalid payload (missing required field) returns HTTP 422
  AC-4  GET returns an array of ModelDefinition objects sorted by cost_per_1k_tokens ASC
  AC-5  GET is served from Redis cache on a second request (cache hit)
  AC-6  Non-admin requests to either endpoint return HTTP 403
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db
from src.main import app
from src.model_registry.dependencies import get_model_registry_service
from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN)
_DEVELOPER_CLAIMS = make_test_claims(PlatformRole.DEVELOPER)

_NOW = datetime(2026, 7, 18, 0, 0, 0, tzinfo=UTC)
_MODEL_ID = uuid4()

_SAMPLE_DEFINITION = ModelDefinition(
    id=_MODEL_ID,
    model_id="gpt-4o-mini",
    provider="openai",
    context_window=128_000,
    cost_per_1k_tokens=0.00015,
    latency_tier=LatencyTier.FAST,
    capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALL],
    is_active=True,
    created_at=_NOW,
    updated_at=_NOW,
)

_VALID_PAYLOAD = {
    "model_id": "gpt-4o-mini",
    "provider": "openai",
    "context_window": 128000,
    "cost_per_1k_tokens": 0.00015,
    "latency_tier": "fast",
    "capabilities": ["chat", "function_call"],
    "is_active": True,
}


def _mock_service(**kwargs: object) -> AsyncMock:
    """Return an AsyncMock with configured method return values or side effects."""
    svc = AsyncMock()
    for method, value in kwargs.items():
        if isinstance(value, Exception):
            getattr(svc, method).side_effect = value
        else:
            getattr(svc, method).return_value = value
    return svc


def _mock_audit() -> AsyncMock:
    """Return a no-op AsyncMock for AuditContext."""
    audit = AsyncMock(spec=AuditContext)
    return audit


# ---------------------------------------------------------------------------
# AC-1: POST success — 201 with ModelDefinition body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_model_returns_201() -> None:
    """AC-1: POST with valid payload returns HTTP 201 and ModelDefinition body."""
    svc = _mock_service(register=_SAMPLE_DEFINITION)
    audit = _mock_audit()
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_model_registry_service] = lambda: svc
    app.dependency_overrides[get_audit_context] = lambda: audit
    app.dependency_overrides[get_db] = _mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/models", json=_VALID_PAYLOAD)
        assert response.status_code == 201
        body = response.json()
        assert body["model_id"] == "gpt-4o-mini"
        assert body["provider"] == "openai"
        assert body["id"] == str(_MODEL_ID)
        svc.register.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_model_registry_service, None)
        app.dependency_overrides.pop(get_audit_context, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-2: POST with duplicate model_id returns 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_model_duplicate_returns_409() -> None:
    """AC-2: POST with a duplicate model_id returns HTTP 409 with an error message."""
    svc = _mock_service(
        register=HTTPException(
            status_code=409, detail="Model 'gpt-4o-mini' is already registered."
        )
    )
    audit = _mock_audit()
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_model_registry_service] = lambda: svc
    app.dependency_overrides[get_audit_context] = lambda: audit
    app.dependency_overrides[get_db] = _mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/models", json=_VALID_PAYLOAD)
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_model_registry_service, None)
        app.dependency_overrides.pop(get_audit_context, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-3: POST with invalid payload returns 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_model_missing_required_field_returns_422() -> None:
    """AC-3: POST with missing required field returns HTTP 422."""
    svc = _mock_service(register=_SAMPLE_DEFINITION)
    audit = _mock_audit()
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    # Omit required 'capabilities' field
    invalid_payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "capabilities"}

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_model_registry_service] = lambda: svc
    app.dependency_overrides[get_audit_context] = lambda: audit
    app.dependency_overrides[get_db] = _mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/models", json=invalid_payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_model_registry_service, None)
        app.dependency_overrides.pop(get_audit_context, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-4: GET returns sorted ModelDefinition list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_returns_sorted_definitions() -> None:
    """AC-4: GET returns array of ModelDefinition objects sorted by cost ASC."""
    cheaper = ModelDefinition(
        id=uuid4(),
        model_id="claude-haiku",
        provider="anthropic",
        context_window=200_000,
        cost_per_1k_tokens=0.00010,
        latency_tier=LatencyTier.FAST,
        capabilities=[ModelCapability.CHAT],
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    costlier = ModelDefinition(
        id=uuid4(),
        model_id="gpt-4o",
        provider="openai",
        context_window=128_000,
        cost_per_1k_tokens=0.005,
        latency_tier=LatencyTier.MEDIUM,
        capabilities=[ModelCapability.CHAT, ModelCapability.VISION],
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    # Service returns already-sorted list (repo orders by cost ASC)
    svc = _mock_service(list_active=[cheaper, costlier])

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # force cache miss
    mock_redis.set = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_model_registry_service] = lambda: svc

    from src.data.dependencies import get_redis_client
    app.dependency_overrides[get_redis_client] = lambda: mock_redis

    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/v1/models")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 2
        assert body[0]["model_id"] == "claude-haiku"
        assert body[1]["model_id"] == "gpt-4o"
        assert body[0]["cost_per_1k_tokens"] < body[1]["cost_per_1k_tokens"]
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_model_registry_service, None)
        app.dependency_overrides.pop(get_redis_client, None)


# ---------------------------------------------------------------------------
# AC-5: GET served from Redis cache on second request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_cache_hit_skips_service() -> None:
    """AC-5: GET is served from Redis cache; service.list_active not called on hit."""
    import json

    cached_data = json.dumps([_SAMPLE_DEFINITION.model_dump(mode="json")])

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=cached_data)
    mock_redis.set = AsyncMock()

    svc = _mock_service(list_active=[_SAMPLE_DEFINITION])

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_model_registry_service] = lambda: svc

    from src.data.dependencies import get_redis_client
    app.dependency_overrides[get_redis_client] = lambda: mock_redis

    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/v1/models")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["model_id"] == "gpt-4o-mini"
        # Cache hit: service.list_active must NOT have been called
        svc.list_active.assert_not_awaited()
        # Redis.set must NOT have been called (no re-population on cache hit)
        mock_redis.set.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_model_registry_service, None)
        app.dependency_overrides.pop(get_redis_client, None)


# ---------------------------------------------------------------------------
# AC-6: Non-admin requests return 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_model_non_admin_returns_403() -> None:
    """AC-6: Non-admin POST returns HTTP 403."""
    app.dependency_overrides[decode_jwt_claims] = lambda: _DEVELOPER_CLAIMS
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/models", json=_VALID_PAYLOAD)
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)


@pytest.mark.asyncio
async def test_list_models_non_admin_returns_403() -> None:
    """AC-6: Non-admin GET returns HTTP 403."""
    app.dependency_overrides[decode_jwt_claims] = lambda: _DEVELOPER_CLAIMS
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/v1/models")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
