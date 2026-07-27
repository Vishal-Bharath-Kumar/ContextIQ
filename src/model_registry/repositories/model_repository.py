"""Async repository for the model_registry table.

Provides all DB operations consumed by ModelRegistryService.

TASK-US018-03 — EP-006 Dynamic Model Routing
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.model_registry.models.model import ModelRecord
from src.model_registry.schemas.model_definition import ModelRegistration


class ModelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_model_id(self, model_id: str) -> ModelRecord | None:
        result = await self._session.execute(
            select(ModelRecord).where(ModelRecord.model_id == model_id)
        )
        return result.scalar_one_or_none()

    async def create(self, registration: ModelRegistration) -> ModelRecord:
        record = ModelRecord(
            model_id=registration.model_id,
            provider=registration.provider,
            context_window=registration.context_window,
            cost_per_1k_tokens=registration.cost_per_1k_tokens,
            latency_tier=registration.latency_tier,
            capabilities=[c.value for c in registration.capabilities],
            is_active=registration.is_active,
        )
        self._session.add(record)
        await self._session.flush()  # get DB-generated id/timestamps before commit
        return record

    async def get_by_id(self, model_id: UUID) -> ModelRecord | None:
        result = await self._session.execute(
            select(ModelRecord).where(ModelRecord.id == model_id)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[ModelRecord]:
        result = await self._session.execute(
            select(ModelRecord)
            .where(ModelRecord.is_active == True)  # noqa: E712
            .order_by(ModelRecord.cost_per_1k_tokens.asc())
        )
        return list(result.scalars().all())
    
    async def list_all(self) -> list[ModelRecord]:
        """Return all models regardless of active status, sorted by cost."""
        result = await self._session.execute(
            select(ModelRecord)
            .order_by(ModelRecord.cost_per_1k_tokens.asc())
        )
        return list(result.scalars().all())

    async def set_active(self, model_id: UUID, is_active: bool) -> ModelRecord | None:
        record = await self.get_by_id(model_id)
        if record is None:
            return None
        record.is_active = is_active
        await self._session.flush()
        return record
