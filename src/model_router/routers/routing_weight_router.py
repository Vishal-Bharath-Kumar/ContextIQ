from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.schemas.intent import IntentType
from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.audit.admin_audit_log.schemas import AdminActionType
from src.auth import require_manage_models
from src.auth.dependencies import JWTClaimsDep
from src.data.dependencies import get_db
from src.model_registry.repositories.model_audit_repository import ModelAuditRepository
from src.model_router.repositories.routing_weight_repository import (
    RoutingWeightRepository,
)
from src.model_router.schemas.routing_weights import RoutingWeights

router = APIRouter(
    prefix="/v1/routing/weights",
    tags=["Routing Weights"],
    dependencies=[Depends(require_manage_models)],
)

_VALID_INTENT_TYPES = {it.value for it in IntentType}


class RoutingWeightResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent_type: str
    quality_weight: float
    cost_weight: float
    latency_weight: float


class RoutingWeightUpdateRequest(BaseModel):
    quality_weight: float
    cost_weight: float
    latency_weight: float

    @model_validator(mode="after")
    def sum_to_one(self) -> RoutingWeightUpdateRequest:
        total = round(self.quality_weight + self.cost_weight + self.latency_weight, 6)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        return self


def _to_serialisable_state(obj: object | None) -> dict | None:
    """Return a JSON-serialisable dict or None for audit logging.

    Accept Pydantic models, plain dicts, or other objects. Falls back to
    a string representation when conversion isn't possible so audit
    logging never raises due to non-serialisable inputs.
    """
    if obj is None:
        return None
    # Pydantic v2 models expose `model_dump()`
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except Exception:
        return {"value": str(obj)}


@router.get(
    "",
    response_model=list[RoutingWeightResponse],
    summary="List effective routing weights for all intent types (AC-3).",
)
async def list_routing_weights(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[RoutingWeightResponse]:
    repo = RoutingWeightRepository(session)
    items = await repo.list_all()
    return [RoutingWeightResponse(**item) for item in items]


@router.put(
    "/{intent_type}",
    response_model=RoutingWeightResponse,
    summary="Override routing weights for a specific intent type (AC-3).",
)
async def update_routing_weights(
    intent_type: str,
    body: RoutingWeightUpdateRequest,
    claims: JWTClaimsDep,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoutingWeightResponse:
    if intent_type not in _VALID_INTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown intent type: {intent_type}",
        )

    repo = RoutingWeightRepository(session)

    before = await repo.get(intent_type)
    await repo.upsert(
        intent_type=intent_type,
        weights=RoutingWeights(
            quality_weight=body.quality_weight,
            cost_weight=body.cost_weight,
            latency_weight=body.latency_weight,
        ),
        actor_user_id=claims.sub,
    )
    # Use safe serialisation for audit entries to avoid unexpected 500s
    # when an object is not directly JSON-serialisable.
    await audit.log(
        action=AdminActionType.MODEL_WEIGHTS_UPDATED,
        resource_type="routing_weight",
        resource_id=intent_type,
        before_state=_to_serialisable_state(before),
        after_state=_to_serialisable_state(body),
    )
    model_audit = ModelAuditRepository(session)
    await model_audit.log(
        model_id=f"routing:{intent_type}",
        event_type="weights_updated",
        actor_user_id=claims.sub,
        detail=(
            f"quality={body.quality_weight} "
            f"cost={body.cost_weight} "
            f"latency={body.latency_weight}"
        ),
    )
    await session.commit()
    return RoutingWeightResponse(
        intent_type=intent_type,
        quality_weight=body.quality_weight,
        cost_weight=body.cost_weight,
        latency_weight=body.latency_weight,
    )
