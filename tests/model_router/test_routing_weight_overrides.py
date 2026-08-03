"""Unit tests for RoutingWeightUpdateRequest validation and RoutingWeightRepository
(TASK-US041-03).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db
from src.main import app
from src.model_router.routers.routing_weight_router import (
    RoutingWeightUpdateRequest,
)
from src.model_router.schemas.routing_weights import RoutingWeights

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN)


# ---------------------------------------------------------------------------
# RoutingWeightUpdateRequest — weight-sum validation
# ---------------------------------------------------------------------------


class TestRoutingWeightUpdateRequest:
    def test_valid_weights_accepted(self) -> None:
        req = RoutingWeightUpdateRequest(
            quality_weight=0.5, cost_weight=0.3, latency_weight=0.2
        )
        assert req.quality_weight == 0.5

    def test_weights_not_summing_to_one_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="sum to 1.0"):
            RoutingWeightUpdateRequest(
                quality_weight=0.5, cost_weight=0.5, latency_weight=0.1
            )

    def test_weights_within_tolerance_accepted(self) -> None:
        # Floating-point edge: 0.333 + 0.333 + 0.334 == 1.0 within 0.001
        req = RoutingWeightUpdateRequest(
            quality_weight=0.333, cost_weight=0.333, latency_weight=0.334
        )
        assert req is not None

    def test_zero_weights_fail(self) -> None:
        with pytest.raises(ValidationError):
            RoutingWeightUpdateRequest(
                quality_weight=0.0, cost_weight=0.0, latency_weight=0.0
            )


# ---------------------------------------------------------------------------
# RoutingWeightRepository — get / upsert / list_all
# ---------------------------------------------------------------------------


class TestRoutingWeightRepository:
    """Tests that exercise the repository logic with a mock AsyncSession."""

    @pytest.fixture()
    def mock_session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_get_returns_db_override_when_present(
        self, mock_session: AsyncMock
    ) -> None:
        from src.model_router.repositories.routing_weight_repository import (
            RoutingWeightRepository,
        )
        from src.model_router.models.routing_weight_override import (
            RoutingWeightOverride,
        )

        override = MagicMock(spec=RoutingWeightOverride)
        override.quality_weight = 0.6
        override.cost_weight = 0.3
        override.latency_weight = 0.1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = override
        mock_session.execute.return_value = mock_result

        repo = RoutingWeightRepository(mock_session)
        result = await repo.get("code-gen")

        assert result.quality_weight == 0.6
        assert result.cost_weight == 0.3
        assert result.latency_weight == 0.1

    @pytest.mark.asyncio
    async def test_get_returns_static_preset_when_no_override(
        self, mock_session: AsyncMock
    ) -> None:
        from src.model_router.repositories.routing_weight_repository import (
            RoutingWeightRepository,
        )
        from src.model_router.schemas.routing_weights import INTENT_ROUTING_WEIGHT_TABLE

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = RoutingWeightRepository(mock_session)
        result = await repo.get("code-gen")

        expected = INTENT_ROUTING_WEIGHT_TABLE["code-gen"]
        assert result == expected

    @pytest.mark.asyncio
    async def test_get_returns_default_for_unknown_intent(
        self, mock_session: AsyncMock
    ) -> None:
        from src.model_router.repositories.routing_weight_repository import (
            RoutingWeightRepository,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = RoutingWeightRepository(mock_session)
        result = await repo.get("unknown-intent")

        # Falls back to default weights
        assert result.quality_weight == 0.4
        assert result.cost_weight == 0.4
        assert result.latency_weight == 0.2

    @pytest.mark.asyncio
    async def test_upsert_executes_and_flushes(
        self, mock_session: AsyncMock
    ) -> None:
        from src.model_router.repositories.routing_weight_repository import (
            RoutingWeightRepository,
        )

        repo = RoutingWeightRepository(mock_session)
        weights = RoutingWeights(
            quality_weight=0.5, cost_weight=0.3, latency_weight=0.2
        )
        await repo.upsert("debugging", weights, actor_user_id="user-1")

        mock_session.execute.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_all_returns_all_eight_intent_types(
        self, mock_session: AsyncMock
    ) -> None:
        from src.model_router.repositories.routing_weight_repository import (
            RoutingWeightRepository,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = RoutingWeightRepository(mock_session)
        items = await repo.list_all()

        assert len(items) == 8
        intent_types = {item["intent_type"] for item in items}
        from src.agents.schemas.intent import IntentType

        assert intent_types == {it.value for it in IntentType}


# ---------------------------------------------------------------------------
# FastAPI routes — HTTP-level tests via src.main.app
# ---------------------------------------------------------------------------


def _make_audit_mock() -> AsyncMock:
    audit = AsyncMock(spec=AuditContext)
    audit.actor_user_id = "test-user"
    return audit


class TestRoutingWeightRoutes:
    @pytest.mark.asyncio
    async def test_put_with_weights_not_summing_to_one_returns_422(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _mock_db():
            yield mock_session

        app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
        app.dependency_overrides[get_audit_context] = _make_audit_mock
        app.dependency_overrides[get_db] = _mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.put(
                    "/v1/routing/weights/debugging",
                    json={
                        "quality_weight": 0.5,
                        "cost_weight": 0.5,
                        "latency_weight": 0.1,
                    },
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(decode_jwt_claims, None)
            app.dependency_overrides.pop(get_audit_context, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_put_unknown_intent_type_returns_404(self) -> None:
        app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
        app.dependency_overrides[get_audit_context] = _make_audit_mock

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        async def _mock_db():
            yield mock_session

        app.dependency_overrides[get_db] = _mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.put(
                    "/v1/routing/weights/nonexistent-type",
                    json={
                        "quality_weight": 0.5,
                        "cost_weight": 0.3,
                        "latency_weight": 0.2,
                    },
                )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(decode_jwt_claims, None)
            app.dependency_overrides.pop(get_audit_context, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_get_list_returns_200_with_all_intents(self) -> None:
        app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        async def _mock_db():
            yield mock_session

        app.dependency_overrides[get_db] = _mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.get("/v1/routing/weights")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 8
        finally:
            app.dependency_overrides.pop(decode_jwt_claims, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_put_valid_weights_stores_override_and_returns_200(self) -> None:
        app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
        app.dependency_overrides[get_audit_context] = _make_audit_mock

        mock_session = AsyncMock()
        # GET before upsert returns no override
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _mock_db():
            yield mock_session

        app.dependency_overrides[get_db] = _mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.put(
                    "/v1/routing/weights/debugging",
                    json={
                        "quality_weight": 0.5,
                        "cost_weight": 0.3,
                        "latency_weight": 0.2,
                    },
                )
            assert response.status_code == 200
            body = response.json()
            assert body["intent_type"] == "debugging"
            assert body["quality_weight"] == 0.5
        finally:
            app.dependency_overrides.pop(decode_jwt_claims, None)
            app.dependency_overrides.pop(get_audit_context, None)
            app.dependency_overrides.pop(get_db, None)
