"""
Replay Explorer API routes — TASK-US035-02.

GET /v1/traces              — AC-1 searchable list, AC-4 RBAC, AC-5 SLA
GET /v1/traces/{request_id} — AC-2 timeline, AC-3 detail fields, AC-5 SLA
GET /v1/traces/{request_id}/export — AC-6 JSON file download
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_auditor
from src.audit.replay.schemas import TraceDetailResponse, TraceListResponse
from src.audit.replay.service import TraceDetailService, TraceNotFoundInIndexError
from src.audit.trace.object_store import TraceObjectStore
from src.audit.trace.repository import TraceIndexRepository, TraceSearchQuery
from src.data.dependencies import get_db, get_redis_client
from src.gateway.schemas.auth_types import JWTClaims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/traces", tags=["Admin — Replay Explorer"])

AuditorClaims = Annotated[JWTClaims, Depends(require_auditor)]


def _resolve_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return str(tenant_id)

    # Local dev remains single-tenant today; traces written by the MCP/graph
    # path are stored under the default tenant when no tenant middleware is set.
    return "default"


def _build_service(session: AsyncSession, redis: aioredis.Redis) -> TraceDetailService:
    repo = TraceIndexRepository(session)
    object_store = TraceObjectStore()
    return TraceDetailService(
        index_repo=repo,
        object_store=object_store,
        cache=redis,
    )


# ------------------------------------------------------------------ #
# GET /v1/traces — AC-1, AC-4, AC-5                                  #
# ------------------------------------------------------------------ #

@router.get(
    "",
    response_model=TraceListResponse,
    summary="Search execution traces (Replay Explorer list view).",
)
async def search_traces(
    request: Request,
    claims: AuditorClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis_client)],
    user_id: str | None = Query(None, description="Filter by user subject claim."),
    intent: str | None = Query(None, description="Filter by intent type."),
    model_selected: str | None = Query(None, description="Filter by model name."),
    governance_blocked: bool | None = Query(None, description="Filter by governance block outcome."),
    from_ts: str | None = Query(None, alias="from", description="ISO-8601 start timestamp (inclusive)."),
    to_ts: str | None = Query(None, alias="to", description="ISO-8601 end timestamp (inclusive)."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> TraceListResponse:
    """
    AC-1: Searchable by user_id, date range, intent type, model used, governance decision.
    AC-4: 403 if caller lacks AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, or ADMIN role.
    AC-5: Served from PostgreSQL index — sub-second for recent traces.
    """
    query = TraceSearchQuery(
        user_id=user_id,
        intent=intent,
        model_selected=model_selected,
        governance_blocked=governance_blocked,
        from_timestamp=datetime.fromisoformat(from_ts) if from_ts else None,
        to_timestamp=datetime.fromisoformat(to_ts) if to_ts else None,
        limit=limit,
        offset=offset,
    )
    svc = _build_service(session, redis)
    tenant_id = _resolve_tenant_id(request)
    return await svc.search(tenant_id, query)


# ------------------------------------------------------------------ #
# GET /v1/traces/{request_id} — AC-2, AC-3, AC-5                     #
# ------------------------------------------------------------------ #

@router.get(
    "/{request_id}",
    response_model=TraceDetailResponse,
    summary="Retrieve full execution trace detail.",
)
async def get_trace_detail(
    request: Request,
    request_id: UUID,
    claims: AuditorClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis_client)],
) -> TraceDetailResponse:
    """
    AC-2: Returns a step-by-step pipeline timeline (TraceDetailResponse.timeline).
    AC-3: Renders all six required detail fields.
    AC-5: Redis cache satisfies 2 s SLA for traces up to 1 year old.
    """
    svc = _build_service(session, redis)
    tenant_id = _resolve_tenant_id(request)
    try:
        return await svc.get_detail(tenant_id, request_id)
    except TraceNotFoundInIndexError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution trace {request_id} not found.",
        ) from None


# ------------------------------------------------------------------ #
# GET /v1/traces/{request_id}/export — AC-6                          #
# ------------------------------------------------------------------ #

@router.get(
    "/{request_id}/export",
    summary="Download full execution trace as a JSON file.",
    response_class=StreamingResponse,
)
async def export_trace(
    request: Request,
    request_id: UUID,
    claims: AuditorClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis_client)],
) -> StreamingResponse:
    """
    AC-6: Returns the raw trace JSON as an attachment download.
    Filename: contextiq-trace-{request_id}.json
    """
    svc = _build_service(session, redis)
    tenant_id = _resolve_tenant_id(request)
    try:
        payload = await svc.get_raw_json(tenant_id, request_id)
    except TraceNotFoundInIndexError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution trace {request_id} not found.",
        ) from None

    filename = f"contextiq-trace-{request_id}.json"
    return StreamingResponse(
        content=iter([payload]),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )
