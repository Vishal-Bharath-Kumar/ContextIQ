"""Tests for ModelAuditRepository and audit logging in mutating model routes.

Verifies AC-6: every mutating model event writes a ModelAuditLog entry
with the correct event_type and actor_user_id.

TASK-US041-05
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
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
# Shared fixtures
# ---------------------------------------------------------------------------

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN, sub="admin-user-id")
_NOW = datetime(2026, 7, 18, 0, 0, 0, tzinfo=UTC)
_MODEL_UUID = uuid4()

_SAMPLE_DEFINITION = ModelDefinition(
    id=_MODEL_UUID,
    model_id="test-model-001",
    provider="openai",
    context_window=8192,
    cost_per_1k_tokens=0.002,
    latency_tier=LatencyTier.FAST,
    capabilities=[ModelCapability.CHAT],
    is_active=True,
    created_at=_NOW,
    updated_at=_NOW,
)

_REGISTER_PAYLOAD = {
    "model_id": "test-model-001",
    "provider": "openai",
    "context_window": 8192,
    "cost_per_1k_tokens": 0.002,
    "latency_tier": "fast",
    "capabilities": ["chat"],
}

_DEACTIVATED_DEFINITION = ModelDefinition(
    id=_MODEL_UUID,
    model_id="test-model-001",
    provider="openai",
    context_window=8192,
    cost_per_1k_tokens=0.002,
    latency_tier=LatencyTier.FAST,
    capabilities=[ModelCapability.CHAT],
    is_active=False,
    created_at=_NOW,
    updated_at=_NOW,
)


def _mock_audit() -> AsyncMock:
    return AsyncMock(spec=AuditContext)


def _mock_db_override(
    session: AsyncMock,
) -> object:
    async def _dep() -> None:
        yield session

    return _dep


# ---------------------------------------------------------------------------
# AC-6: POST /v1/models writes a 'registered' audit entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_model_writes_audit_entry() -> None:
    """AC-6: POST /v1/models inserts a 'registered' audit row with actor_user_id."""
    svc = AsyncMock()
    svc.register = AsyncMock(return_value=_SAMPLE_DEFINITION)
    mock_session = AsyncMock()

    with patch(
        "src.model_registry.routers.model_router.ModelAuditRepository"
    ) as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
        app.dependency_overrides[get_model_registry_service] = lambda: svc
        app.dependency_overrides[get_audit_context] = lambda: _mock_audit()
        app.dependency_overrides[get_db] = _mock_db_override(mock_session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                r = await client.post("/v1/models", json=_REGISTER_PAYLOAD)
            assert r.status_code == 201

            mock_repo.log.assert_awaited_once()
            kwargs = mock_repo.log.call_args.kwargs
            assert kwargs["model_id"] == "test-model-001"
            assert kwargs["event_type"] == "registered"
            assert kwargs["actor_user_id"] == _ADMIN_CLAIMS.sub
            assert "provider=openai" in (kwargs.get("detail") or "")
        finally:
            app.dependency_overrides.pop(decode_jwt_claims, None)
            app.dependency_overrides.pop(get_model_registry_service, None)
            app.dependency_overrides.pop(get_audit_context, None)
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-5 + AC-6: PATCH /v1/models/{id}/status writes 'status_changed' entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_model_writes_audit_entry() -> None:
    """AC-5 + AC-6: PATCH /status inserts a 'status_changed' entry with is_active=False."""
    svc = AsyncMock()
    svc.set_active = AsyncMock(return_value=_DEACTIVATED_DEFINITION)
    mock_session = AsyncMock()

    with patch(
        "src.model_registry.routers.model_router.ModelAuditRepository"
    ) as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
        app.dependency_overrides[get_model_registry_service] = lambda: svc
        app.dependency_overrides[get_audit_context] = lambda: _mock_audit()
        app.dependency_overrides[get_db] = _mock_db_override(mock_session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                r = await client.patch(
                    f"/v1/models/{_MODEL_UUID}/status",
                    json={"is_active": False},
                )
            assert r.status_code == 200

            mock_repo.log.assert_awaited_once()
            kwargs = mock_repo.log.call_args.kwargs
            assert kwargs["model_id"] == "test-model-001"
            assert kwargs["event_type"] == "status_changed"
            assert kwargs["actor_user_id"] == _ADMIN_CLAIMS.sub
            assert "is_active=False" in (kwargs.get("detail") or "")
        finally:
            app.dependency_overrides.pop(decode_jwt_claims, None)
            app.dependency_overrides.pop(get_model_registry_service, None)
            app.dependency_overrides.pop(get_audit_context, None)
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-3 + AC-6: PUT /v1/routing/weights/{intent_type} writes 'weights_updated'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routing_weight_update_writes_audit_entry() -> None:
    """AC-3 + AC-6: PUT /routing/weights inserts a 'weights_updated' entry."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_audit = AsyncMock(spec=AuditContext)
    mock_audit.actor_user_id = "admin-user-id"

    with patch(
        "src.model_router.routers.routing_weight_router.ModelAuditRepository"
    ) as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
        app.dependency_overrides[get_audit_context] = lambda: mock_audit
        app.dependency_overrides[get_db] = _mock_db_override(mock_session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                r = await client.put(
                    "/v1/routing/weights/code-gen",
                    json={
                        "quality_weight": 0.60,
                        "cost_weight": 0.30,
                        "latency_weight": 0.10,
                    },
                )
            assert r.status_code == 200

            mock_repo.log.assert_awaited_once()
            kwargs = mock_repo.log.call_args.kwargs
            assert kwargs["model_id"] == "routing:code-gen"
            assert kwargs["event_type"] == "weights_updated"
            assert kwargs["actor_user_id"] == _ADMIN_CLAIMS.sub
        finally:
            app.dependency_overrides.pop(decode_jwt_claims, None)
            app.dependency_overrides.pop(get_audit_context, None)
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Unit test: ModelAuditRepository.log() adds entry and flushes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_audit_repository_log_adds_and_flushes() -> None:
    """ModelAuditRepository.log() calls session.add() and session.flush()."""
    from src.model_registry.repositories.model_audit_repository import (
        ModelAuditRepository,
    )

    mock_session = AsyncMock()
    repo = ModelAuditRepository(mock_session)
    await repo.log(
        model_id="gpt-4o",
        event_type="registered",
        actor_user_id="user-123",
        detail="provider=openai",
    )
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()
    added_entry = mock_session.add.call_args[0][0]
    assert added_entry.model_id == "gpt-4o"
    assert added_entry.event_type == "registered"
    assert added_entry.actor_user_id == "user-123"
    assert added_entry.detail == "provider=openai"
