"""FastAPI dependency providers for the Model Registry module.

TASK-US018-04: POST /v1/models and GET /v1/models API Endpoints.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.dependencies import get_db, get_redis_client
from src.model_registry.services.model_registry_service import ModelRegistryService


async def get_model_registry_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> ModelRegistryService:
    """Construct a ModelRegistryService with injected DB session and Redis client."""
    return ModelRegistryService(session=session, redis=redis)
