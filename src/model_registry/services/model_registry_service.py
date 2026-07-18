"""Business logic for the Model Capability Registry lifecycle.

Provides CRUD operations for model definitions with a 409 duplicate guard
and Redis pub/sub invalidation after every mutation.

Pub/sub channel: contextiq:model_registry:changed

TASK-US018-03 — EP-006 Dynamic Model Routing
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.model_registry.repositories.model_repository import ModelRepository
from src.model_registry.schemas.model_definition import ModelDefinition, ModelRegistration

REGISTRY_CHANGE_CHANNEL = "contextiq:model_registry:changed"  # mirrors tool registry pattern


class ModelRegistryService:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._repo = ModelRepository(session)
        self._redis = redis

    async def register(self, registration: ModelRegistration) -> ModelDefinition:
        existing = await self._repo.get_by_model_id(registration.model_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Model '{registration.model_id}' is already registered.",
            )
        record = await self._repo.create(registration)
        await self._session.commit()
        await self._publish_change_event(registration.model_id)
        return ModelDefinition.model_validate(record)

    async def list_active(self) -> list[ModelDefinition]:
        records = await self._repo.list_active()
        return [ModelDefinition.model_validate(r) for r in records]

    async def set_active(self, model_id: UUID, is_active: bool) -> ModelDefinition:
        record = await self._repo.set_active(model_id, is_active)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")
        await self._session.commit()
        await self._publish_change_event(record.model_id)
        return ModelDefinition.model_validate(record)

    async def _publish_change_event(self, model_id: str) -> None:
        payload = json.dumps({"event": "model_registered", "model_id": model_id})
        await self._redis.publish(REGISTRY_CHANGE_CHANNEL, payload)
