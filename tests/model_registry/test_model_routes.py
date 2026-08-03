"""Integration-style tests for Model Registry API routes — TASK-US041-05.

Covers the remaining US-041 acceptance criteria not already tested in
tests/model_registry/test_model_router.py:

  AC-1  GET /v1/models returns active models with all required fields
  AC-2  Duplicate model_id returns HTTP 409
  AC-3  Routing weights with invalid sum return HTTP 422
  AC-4  GET /v1/models/cost-analytics returns list response

All tests use httpx.AsyncClient with mocked dependencies — no real DB or
Redis connection required.
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
from src.data.dependencies import get_db, get_redis_client
from src.main import app
from src.model_registry.dependencies import get_model_registry_service
from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
)

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN)
_NOW = datetime(2026, 7, 18, 0, 0, 0, tzinfo=UTC)


def _mock_audit() -> AsyncMock:
    return AsyncMock(spec=AuditContext)


def _sample_definition(**overrides: object) -> ModelDefinition:
    defaults: dict = {
        "id": uuid4(),
        "model_id": "gpt-4o-mini",
        "provider": "openai",
        "context_window": 128_000,
        "cost_per_1k_tokens": 0.00015,
        "latency_tier": LatencyTier.FAST,
        "capabilities": [ModelCapability.CHAT, ModelCapability.FUNCTION_CALL],
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return ModelDefinition(**defaults)  # type: ignore[arg-type]


def _mock_db_override(
    session: AsyncMock,
) -> object:
    async def _dep() -> None:
        yield session

    return _dep


# ---------------------------------------------------------------------------
# AC-1: GET /v1/models returns active models with required fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_list_returns_active_models() -> None:
    """AC-1: GET /v1/models returns active models with all required fields."""
    model = _sample_definition()
    svc = AsyncMock()
    svc.list_active = AsyncMock(return_value=[model])

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_model_registry_service] = lambda: svc
    app.dependency_overrides[get_redis_client] = lambda: mock_redis
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            r = await client.get("/v1/models")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        m = data[0]
        assert all(
            k in m
            for k in [
                "model_id",
                "provider",
                "context_window",
                "cost_per_1k_tokens",
                "latency_tier",
                "capabilities",
                "is_active",
            ]
        )
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_model_registry_service, None)
        app.dependency_overrides.pop(get_redis_client, None)


# ---------------------------------------------------------------------------
# AC-2: Duplicate model_id returns HTTP 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_duplicate_model_returns_409() -> None:
    """AC-2: duplicate model_id returns HTTP 409."""
    svc = AsyncMock()
    svc.register = AsyncMock(
        side_effect=HTTPException(
            status_code=409, detail="Model 'gpt-4o-mini' is already registered."
        )
    )
    mock_session = AsyncMock()
    payload = {
        "model_id": "gpt-4o-mini",
        "provider": "openai",
        "context_window": 128000,
        "cost_per_1k_tokens": 0.00015,
        "latency_tier": "fast",
        "capabilities": ["chat"],
    }

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_model_registry_service] = lambda: svc
    app.dependency_overrides[get_audit_context] = lambda: _mock_audit()
    app.dependency_overrides[get_db] = _mock_db_override(mock_session)
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            r = await client.post("/v1/models", json=payload)
        assert r.status_code == 409
        assert "already registered" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_model_registry_service, None)
        app.dependency_overrides.pop(get_audit_context, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-3: Routing weights with invalid sum return HTTP 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routing_weights_reject_non_summing_weights() -> None:
    """AC-3: weights not summing to 1.0 return HTTP 422."""
    mock_session = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_audit_context] = lambda: _mock_audit()
    app.dependency_overrides[get_db] = _mock_db_override(mock_session)
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            r = await client.put(
                "/v1/routing/weights/code-gen",
                json={
                    "quality_weight": 0.5,
                    "cost_weight": 0.5,
                    "latency_weight": 0.5,
                },
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_audit_context, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-4: GET /v1/models/cost-analytics returns list response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_analytics_returns_list_response() -> None:
    """AC-4: GET /v1/models/cost-analytics returns a JSON list of ModelCostSummary."""
    from unittest.mock import patch as _patch

    from src.auth import require_cost_analytics

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[require_cost_analytics] = lambda: _ADMIN_CLAIMS
    try:
        with _patch(
            "src.api.admin.routes.model_analytics.ModelCostAnalyticsService"
        ) as mock_cls:
            mock_svc = AsyncMock()
            mock_svc.get_model_cost_summary = AsyncMock(return_value=[])
            mock_cls.return_value = mock_svc

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                r = await client.get("/v1/models/cost-analytics?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(require_cost_analytics, None)
