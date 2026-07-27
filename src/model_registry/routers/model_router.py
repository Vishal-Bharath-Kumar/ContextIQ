"""HTTP routes for the Model Capability Registry.

POST   /v1/models      — register a new model (AC-1 / AC-2)
POST   /v1/models/install — install model with credentials
POST   /v1/models/ollama/pull — pull Ollama model
GET    /v1/models?include_inactive=true — list models (defaults to all); Redis-cached
GET    /v1/models/ollama — list available Ollama models
PATCH  /v1/models/{id}/status — toggle is_active (AC-5)
DELETE /v1/models/{id} — delete model from registry and optionally from Ollama

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
from src.model_registry.schemas.model_installation import (
    ModelInstallationRequest,
    ModelInstallationResponse,
    OllamaModelInfo,
    OllamaPullRequest,
    OllamaPullResponse,
)
from src.model_registry.services.model_registry_service import ModelRegistryService
from src.model_registry.services.ollama_service import OllamaService

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
    include_inactive: bool = True,
) -> list[ModelDefinition]:
    """List models; include_inactive=true shows all, false shows only active; Redis-cached."""
    cache_key = f"{_CACHE_KEY}:all" if include_inactive else _CACHE_KEY
    
    cached = await redis.get(cache_key)
    if cached is not None:
        return [ModelDefinition.model_validate(m) for m in json.loads(cached)]
    
    models = await service.list_all() if include_inactive else await service.list_active()
    await redis.set(
        cache_key,
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
    redis: Annotated[Redis, Depends(get_redis_client)],
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
    # Invalidate both cache keys (all models and active-only)
    import logging
    logger = logging.getLogger(__name__)
    try:
        deleted_count = 0
        deleted_count += await redis.delete(_CACHE_KEY)
        deleted_count += await redis.delete(f"{_CACHE_KEY}:all")
        logger.info(f"Cache invalidation: deleted {deleted_count} cache keys for status change")
    except Exception as e:
        logger.error(f"Failed to invalidate cache after status change: {e}")
    return result


@router.post("/install", status_code=201, response_model=ModelInstallationResponse)
async def install_model(
    body: ModelInstallationRequest,
    claims: JWTClaimsDep,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    service: Annotated[ModelRegistryService, Depends(get_model_registry_service)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ModelInstallationResponse:
    """Install a new model with credentials (API-based or Ollama)."""
    result = await service.install_model(body)
    
    await audit.log(
        action=AdminActionType.MODEL_REGISTERED,
        resource_type="model",
        resource_id=result.model_id,
        before_state=None,
        after_state={"provider_type": result.provider_type, "status": result.status},
    )
    await session.commit()
    return result


@router.get("/ollama", response_model=list[OllamaModelInfo])
async def list_ollama_models() -> list[OllamaModelInfo]:
    """List all downloaded Ollama models."""
    ollama_service = OllamaService()
    return await ollama_service.list_models()


@router.post("/ollama/pull", response_model=OllamaPullResponse)
async def pull_ollama_model(
    body: OllamaPullRequest,
    claims: JWTClaimsDep,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> OllamaPullResponse:
    """Pull/download an Ollama model."""
    ollama_service = OllamaService()
    result = await ollama_service.pull_model(body)
    
    await audit.log(
        action=AdminActionType.MODEL_REGISTERED,
        resource_type="ollama_model",
        resource_id=body.model_name,
        before_state=None,
        after_state={"status": result.status},
    )
    await session.commit()
    return result


@router.delete("/{model_id}", response_model=dict)
async def delete_model(
    model_id: UUID,
    claims: JWTClaimsDep,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    service: Annotated[ModelRegistryService, Depends(get_model_registry_service)],
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    delete_from_ollama: bool = False,
) -> dict[str, str]:
    """Delete a model from the registry and optionally from Ollama."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[DELETE] Starting deletion for model_id={model_id}, delete_from_ollama={delete_from_ollama}")
    
    # Delegate everything to the service which handles the full deletion
    result = await service.delete_model(model_id, delete_from_ollama)
    logger.info(f"[DELETE] Service returned: {result}")
    
    # Flush to ensure deletion is staged before audit logging
    await session.flush()
    logger.info("[DELETE] Session flushed")
    
    # Add audit log
    model_audit = ModelAuditRepository(session)
    await model_audit.log(
        model_id=result["model_id"],
        event_type="deleted",
        actor_user_id=claims.sub,
        detail=f"delete_from_ollama={delete_from_ollama}",
    )
    logger.info("[DELETE] Model audit logged")
    
    await audit.log(
        action=AdminActionType.MODEL_STATUS_CHANGED,
        resource_type="model",
        resource_id=str(model_id),
        before_state={"model_id": result["model_id"], "provider": result.get("provider")},
        after_state=None,
    )
    logger.info("[DELETE] Admin audit logged")
    
    # Commit all changes (delete + audit logs)
    await session.commit()
    logger.info("[DELETE] Session committed")
    
    # Invalidate both cache keys after successful commit
    try:
        # Delete both cache variants
        deleted_count = 0
        deleted_count += await redis.delete(_CACHE_KEY)
        deleted_count += await redis.delete(f"{_CACHE_KEY}:all")
        logger.info(f"[DELETE] Cache invalidation: deleted {deleted_count} cache keys")
    except Exception as e:
        # Log the error but don't fail the request
        logger.error(f"[DELETE] Failed to invalidate cache: {e}")
    
    logger.info(f"[DELETE] Completed successfully, returning: {result}")
    return result

