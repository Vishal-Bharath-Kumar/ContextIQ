"""HTTP routes for the Model Capability Registry.

POST /v1/models      — register a new model (AC-1 / AC-2)
GET  /v1/models      — list active models, Redis-cached (AC-1 / AC-4 / AC-5)
PATCH /v1/models/{id}/status — toggle is_active (AC-5)

All mutating routes write a ModelAuditLog entry (AC-6).

TASK-US018-04 / TASK-US041-05
"""
from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.audit.admin_audit_log.schemas import AdminActionType
from src.auth import require_manage_models
from src.auth.dependencies import JWTClaimsDep
from src.data.dependencies import get_db, get_redis_client
from src.model_registry.dependencies import get_model_registry_service
from src.model_registry.repositories.model_audit_repository import ModelAuditRepository
from src.model_registry.schemas.model_definition import ModelDefinition, ModelRegistration
from src.model_registry.services.model_registry_service import ModelRegistryService

_CACHE_KEY = "model_registry:active_models"
_CACHE_TTL = 60  # seconds


class ModelStatusUpdateRequest(BaseModel):
    is_active: bool


router = APIRouter(
    prefix="/v1/models",
    tags=["Model Registry"],
    dependencies=[Depends(require_manage_models)],
)


@router.get("", response_model=list[ModelDefinition])
async def list_models(
    service: Annotated[ModelRegistryService, Depends(get_model_registry_service)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> list[ModelDefinition]:
    """AC-1 / AC-4 / AC-5: return active models sorted by cost; Redis-cached."""
    cached = await redis.get(_CACHE_KEY)
    if cached is not None:
        return [ModelDefinition.model_validate(m) for m in json.loads(cached)]
    models = await service.list_active()
    await redis.set(
        _CACHE_KEY,
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=_CACHE_TTL,
    )
    return models


@router.post("", status_code=201, response_model=ModelDefinition)
async def register_model(
    body: ModelRegistration,
    claims: JWTClaimsDep,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    service: Annotated[ModelRegistryService, Depends(get_model_registry_service)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ModelDefinition:
    """AC-1 / AC-2: register a model; logs MODEL_REGISTERED audit entry (AC-6)."""
    result = await service.register(body)
    model_audit = ModelAuditRepository(session)
    await model_audit.log(
        model_id=result.model_id,
        event_type="registered",
        actor_user_id=claims.sub,
        detail=f"provider={result.provider} latency={result.latency_tier}",
    )
    await audit.log(
        action=AdminActionType.MODEL_REGISTERED,
        resource_type="model",
        resource_id=str(result.id),
        before_state=None,
        after_state=result.model_dump(mode="json"),
    )
    await session.commit()
    return result


@router.patch("/{model_id}/status", response_model=ModelDefinition)
async def update_model_status(
    model_id: UUID,
    body: ModelStatusUpdateRequest,
    claims: JWTClaimsDep,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    service: Annotated[ModelRegistryService, Depends(get_model_registry_service)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ModelDefinition:
    """AC-5: toggle model activation; logs MODEL_STATUS_CHANGED audit entry (AC-6)."""
    result = await service.set_active(model_id, body.is_active)
    model_audit = ModelAuditRepository(session)
    await model_audit.log(
        model_id=result.model_id,
        event_type="status_changed",
        actor_user_id=claims.sub,
        detail=f"is_active={body.is_active}",
    )
    await audit.log(
        action=AdminActionType.MODEL_STATUS_CHANGED,
        resource_type="model",
        resource_id=str(model_id),
        before_state={"is_active": not body.is_active},
        after_state={"is_active": body.is_active},
    )
    await session.commit()
    return result
