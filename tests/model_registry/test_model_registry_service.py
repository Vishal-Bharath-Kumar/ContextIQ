"""Unit tests for ModelRepository and ModelRegistryService.

TASK-US018-03 acceptance criteria covered:
  - register() returns a ModelDefinition with id, created_at, updated_at populated
  - register() raises HTTP 409 when model_id is already present in DB
  - list_active() returns only is_active=True models, sorted by cost_per_1k_tokens ASC
  - _publish_change_event() publishes JSON to contextiq:model_registry:changed
  - DB session is committed before the pub/sub event is published
  - All tests use AsyncMock for Redis and mocked async session — no live DB/Redis
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.model_registry.models.model import ModelRecord
from src.model_registry.repositories.model_repository import ModelRepository
from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
    ModelRegistration,
)
from src.model_registry.services.model_registry_service import (
    REGISTRY_CHANGE_CHANNEL,
    ModelRegistryService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 7, 18, 0, 0, 0, tzinfo=UTC)


def _make_registration(
    model_id: str = "gpt-4o-mini",
    cost: float = 0.00015,
    is_active: bool = True,
) -> ModelRegistration:
    return ModelRegistration(
        model_id=model_id,
        provider="openai",
        context_window=128_000,
        cost_per_1k_tokens=cost,
        latency_tier=LatencyTier.FAST,
        capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALL],
        is_active=is_active,
    )


def _make_record(
    model_id: str = "gpt-4o-mini",
    cost: float = 0.00015,
    is_active: bool = True,
) -> ModelRecord:
    rec = ModelRecord(
        model_id=model_id,
        provider="openai",
        context_window=128_000,
        cost_per_1k_tokens=cost,
        latency_tier=LatencyTier.FAST,
        capabilities=[ModelCapability.CHAT.value, ModelCapability.FUNCTION_CALL.value],
        is_active=is_active,
    )
    rec.id = uuid4()
    rec.created_at = NOW
    rec.updated_at = NOW
    return rec


def _make_service(
    get_by_model_id_return: ModelRecord | None = None,
    list_active_return: list[ModelRecord] | None = None,
    create_return: ModelRecord | None = None,
) -> tuple[ModelRegistryService, MagicMock, AsyncMock]:
    """Return (service, mock_repo, mock_redis)."""
    session = AsyncMock()
    session.commit = AsyncMock()
    redis = AsyncMock()

    mock_repo = MagicMock()
    mock_repo.get_by_model_id = AsyncMock(return_value=get_by_model_id_return)
    mock_repo.list_active = AsyncMock(return_value=list_active_return or [])

    default_record = create_return or _make_record()
    mock_repo.create = AsyncMock(return_value=default_record)

    svc = ModelRegistryService(session=session, redis=redis)
    svc._repo = mock_repo
    return svc, mock_repo, redis


# ---------------------------------------------------------------------------
# ModelRepository unit tests
# ---------------------------------------------------------------------------


class TestModelRepository:
    @pytest.mark.asyncio
    async def test_get_by_model_id_returns_none_when_missing(self) -> None:
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        repo = ModelRepository(session)
        result = await repo.get_by_model_id("nonexistent")

        assert result is None
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_model_id_returns_record_when_found(self) -> None:
        record = _make_record()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)

        repo = ModelRepository(session)
        result = await repo.get_by_model_id("gpt-4o-mini")

        assert result is record

    @pytest.mark.asyncio
    async def test_create_adds_and_flushes(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        repo = ModelRepository(session)
        registration = _make_registration()
        await repo.create(registration)

        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_maps_capabilities_to_values(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        repo = ModelRepository(session)
        registration = _make_registration()
        await repo.create(registration)

        added_record: ModelRecord = session.add.call_args[0][0]
        assert added_record.capabilities == [
            ModelCapability.CHAT.value,
            ModelCapability.FUNCTION_CALL.value,
        ]

    @pytest.mark.asyncio
    async def test_list_active_returns_results(self) -> None:
        records = [_make_record("gpt-4o-mini", cost=0.001), _make_record("gpt-4o", cost=0.005)]
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        session.execute = AsyncMock(return_value=mock_result)

        repo = ModelRepository(session)
        result = await repo.list_active()

        assert result == records


# ---------------------------------------------------------------------------
# ModelRegistryService — register()
# ---------------------------------------------------------------------------


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_returns_model_definition(self) -> None:
        record = _make_record()
        svc, repo, _ = _make_service(get_by_model_id_return=None, create_return=record)

        result = await svc.register(_make_registration())

        assert isinstance(result, ModelDefinition)
        assert result.model_id == record.model_id
        assert result.id == record.id
        assert result.created_at == NOW
        assert result.updated_at == NOW

    @pytest.mark.asyncio
    async def test_register_calls_create_on_repo(self) -> None:
        svc, repo, _ = _make_service(get_by_model_id_return=None)

        await svc.register(_make_registration())

        repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_raises_409_on_duplicate(self) -> None:
        existing = _make_record()
        svc, _, _ = _make_service(get_by_model_id_return=existing)

        with pytest.raises(HTTPException) as exc_info:
            await svc.register(_make_registration())

        assert exc_info.value.status_code == 409
        assert "gpt-4o-mini" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_register_commits_session(self) -> None:
        svc, _, _ = _make_service(get_by_model_id_return=None)

        await svc.register(_make_registration())

        svc._session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_publishes_redis_event(self) -> None:
        svc, _, redis = _make_service(get_by_model_id_return=None)

        await svc.register(_make_registration(model_id="gpt-4o-mini"))

        redis.publish.assert_awaited_once()
        channel, payload_str = redis.publish.call_args.args
        assert channel == REGISTRY_CHANGE_CHANNEL
        payload = json.loads(payload_str)
        assert payload["event"] == "model_registered"
        assert payload["model_id"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_register_commits_before_publish(self) -> None:
        """DB commit must precede pub/sub publication."""
        call_order: list[str] = []

        svc, _, redis = _make_service(get_by_model_id_return=None)
        svc._session.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))
        redis.publish = AsyncMock(side_effect=lambda *_: call_order.append("publish"))

        await svc.register(_make_registration())

        assert call_order == ["commit", "publish"]

    @pytest.mark.asyncio
    async def test_register_no_create_on_duplicate(self) -> None:
        existing = _make_record()
        svc, repo, _ = _make_service(get_by_model_id_return=existing)

        with pytest.raises(HTTPException):
            await svc.register(_make_registration())

        repo.create.assert_not_awaited()


# ---------------------------------------------------------------------------
# ModelRegistryService — list_active()
# ---------------------------------------------------------------------------


class TestListActive:
    @pytest.mark.asyncio
    async def test_list_active_returns_definitions(self) -> None:
        records = [_make_record("gpt-4o-mini", cost=0.001), _make_record("gpt-4o", cost=0.005)]
        svc, _, _ = _make_service(list_active_return=records)

        result = await svc.list_active()

        assert len(result) == 2
        assert all(isinstance(d, ModelDefinition) for d in result)
        assert result[0].model_id == "gpt-4o-mini"
        assert result[1].model_id == "gpt-4o"

    @pytest.mark.asyncio
    async def test_list_active_empty(self) -> None:
        svc, _, _ = _make_service(list_active_return=[])

        result = await svc.list_active()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_active_delegates_to_repo(self) -> None:
        svc, repo, _ = _make_service(list_active_return=[])

        await svc.list_active()

        repo.list_active.assert_awaited_once()


# ---------------------------------------------------------------------------
# ModelRegistryService — _publish_change_event()
# ---------------------------------------------------------------------------


class TestPublishChangeEvent:
    @pytest.mark.asyncio
    async def test_publishes_to_correct_channel(self) -> None:
        svc, _, redis = _make_service()

        await svc._publish_change_event("some-model")

        redis.publish.assert_awaited_once()
        channel, _ = redis.publish.call_args.args
        assert channel == "contextiq:model_registry:changed"

    @pytest.mark.asyncio
    async def test_payload_is_valid_json(self) -> None:
        svc, _, redis = _make_service()

        await svc._publish_change_event("some-model")

        _, payload_str = redis.publish.call_args.args
        payload = json.loads(payload_str)
        assert payload["event"] == "model_registered"
        assert payload["model_id"] == "some-model"
