from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.schemas.intent import IntentType
from src.model_router.models.routing_weight_override import RoutingWeightOverride
from src.model_router.schemas.routing_weights import (
    INTENT_ROUTING_WEIGHT_TABLE,
    RoutingWeights,
)

_DEFAULT_WEIGHTS = RoutingWeights(
    quality_weight=0.4, cost_weight=0.4, latency_weight=0.2
)


class RoutingWeightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, intent_type: str) -> RoutingWeights:
        """Return DB override if present, else the static preset."""
        row = (
            await self._session.execute(
                select(RoutingWeightOverride).where(
                    RoutingWeightOverride.intent_type == intent_type
                )
            )
        ).scalar_one_or_none()

        if row:
            return RoutingWeights(
                quality_weight=row.quality_weight,
                cost_weight=row.cost_weight,
                latency_weight=row.latency_weight,
            )
        return INTENT_ROUTING_WEIGHT_TABLE.get(intent_type, _DEFAULT_WEIGHTS)

    async def upsert(
        self,
        intent_type: str,
        weights: RoutingWeights,
        actor_user_id: str,
    ) -> None:
        """INSERT … ON CONFLICT (intent_type) DO UPDATE — idempotent."""
        stmt = (
            pg_insert(RoutingWeightOverride)
            .values(
                intent_type=intent_type,
                quality_weight=weights.quality_weight,
                cost_weight=weights.cost_weight,
                latency_weight=weights.latency_weight,
                updated_by=actor_user_id,
            )
            .on_conflict_do_update(
                index_elements=["intent_type"],
                set_={
                    "quality_weight": weights.quality_weight,
                    "cost_weight": weights.cost_weight,
                    "latency_weight": weights.latency_weight,
                    "updated_by": actor_user_id,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_all(self) -> list[dict[str, Any]]:
        """Return all intent types with their effective weights (override or static)."""
        return [
            {
                "intent_type": it.value,
                **(await self.get(it.value)).model_dump(),
            }
            for it in IntentType
        ]
