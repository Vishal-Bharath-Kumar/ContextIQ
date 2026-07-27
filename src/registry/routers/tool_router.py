"""
Admin REST API for the tool registry lifecycle.

TASK-US002-02:
  POST   /v1/tools          — register a new tool (201)
  GET    /v1/tools          — list tools, optional ?status=active|inactive
  GET    /v1/tools/{name}   — fetch single tool by name
  PATCH  /v1/tools/{name}   — update description, schema, status, or version
  DELETE /v1/tools/{name}   — soft-delete (sets status = 'inactive'), or hard-delete with ?hard_delete=true

RBAC: POST / PATCH / DELETE require ADMIN or PLATFORM_ENGINEER role.
GET endpoints require the same guard (read is also privileged for tool definitions).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin, require_platform_engineer, require_roles
from src.auth.roles import PlatformRole
from src.data.dependencies import get_db
from src.data.redis_client import create_redis_client
from src.registry.models.tool import ToolStatus
from src.registry.services.tool_registry_service import (
    DuplicateToolError,
    ToolNotFoundError,
    ToolRegistryService,
)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ToolCreateRequest(BaseModel):
    name: str = Field(..., max_length=128)
    description: str
    inputSchema: dict[str, Any] = Field(default_factory=dict)
    version: str = Field(default="1.0.0", max_length=32)


class ToolUpdateRequest(BaseModel):
    description: str | None = None
    inputSchema: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    version: str | None = Field(default=None, max_length=32)


class ToolResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    inputSchema: dict[str, Any]
    status: str
    version: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_tool(cls, tool: Any) -> "ToolResponse":
        return cls(
            id=tool.id,
            name=tool.name,
            description=tool.description,
            inputSchema=tool.input_schema,
            status=tool.status,
            version=tool.version,
            created_at=tool.created_at,
            updated_at=tool.updated_at,
        )


# ---------------------------------------------------------------------------
# Dependency: build the service with DB session + Redis client
# ---------------------------------------------------------------------------

_require_admin_or_pe = require_roles(PlatformRole.ADMIN, PlatformRole.PLATFORM_ENGINEER)


def _get_redis() -> Any:
    return create_redis_client()


async def _get_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Any, Depends(_get_redis)],
) -> ToolRegistryService:
    return ToolRegistryService(session=session, redis_client=redis)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/v1/tools",
    tags=["Tool Registry"],
    dependencies=[Depends(_require_admin_or_pe)],
)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ToolResponse)
async def register_tool(
    body: ToolCreateRequest,
    svc: Annotated[ToolRegistryService, Depends(_get_service)],
) -> ToolResponse:
    try:
        tool = await svc.create_tool(
            name=body.name,
            description=body.description,
            input_schema=body.inputSchema,
            version=body.version,
        )
    except DuplicateToolError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ToolResponse.from_orm_tool(tool)


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    svc: Annotated[ToolRegistryService, Depends(_get_service)],
    tool_status: str | None = Query(default=None, alias="status", pattern="^(active|inactive)$"),
) -> list[ToolResponse]:
    filter_status = ToolStatus(tool_status) if tool_status else None
    tools = await svc.list_tools(status=filter_status)
    return [ToolResponse.from_orm_tool(t) for t in tools]


@router.get("/{name}", response_model=ToolResponse)
async def get_tool(
    name: str,
    svc: Annotated[ToolRegistryService, Depends(_get_service)],
) -> ToolResponse:
    try:
        tool = await svc.get_tool(name)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ToolResponse.from_orm_tool(tool)


@router.patch("/{name}", response_model=ToolResponse)
async def update_tool(
    name: str,
    body: ToolUpdateRequest,
    svc: Annotated[ToolRegistryService, Depends(_get_service)],
) -> ToolResponse:
    try:
        tool = await svc.update_tool(
            name=name,
            description=body.description,
            input_schema=body.inputSchema,
            status=body.status,
            version=body.version,
        )
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ToolResponse.from_orm_tool(tool)


@router.delete("/{name}", response_model=ToolResponse)
async def delete_tool(
    name: str,
    svc: Annotated[ToolRegistryService, Depends(_get_service)],
    hard_delete: bool = Query(default=False, description="If true, permanently delete the tool from database"),
) -> ToolResponse:
    try:
        if hard_delete:
            tool = await svc.hard_delete_tool(name)
        else:
            tool = await svc.delete_tool(name)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ToolResponse.from_orm_tool(tool)
