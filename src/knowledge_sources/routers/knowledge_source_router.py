"""Knowledge Source Admin API routes — TASK-US025-04 / TASK-US026-04.

Registers:
  POST /v1/knowledge-sources
  GET  /v1/knowledge-sources
  PATCH /v1/knowledge-sources/{source_id}/status
  POST /v1/knowledge-sources/{source_id}/sync
  GET  /v1/knowledge-sources/{source_id}/sync/{job_id}

All routes require admin JWT.
"""
from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin
from src.data.database import primary_session_factory
from src.data.dependencies import get_db
from src.knowledge_sources.dependencies import get_knowledge_source_service
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository
from src.knowledge_sources.schemas.knowledge_source import (
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
)
from src.knowledge_sources.schemas.sync_job import SyncJobResponse
from src.knowledge_sources.services.knowledge_source_service import KnowledgeSourceService
from src.knowledge_sources.sync.executor import SyncJobExecutor

router = APIRouter(
    prefix="/v1/knowledge-sources",
    tags=["Knowledge Sources"],
    dependencies=[Depends(require_admin)],
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=KnowledgeSourceResponse,
    summary="Register a new knowledge source",
)
async def create_knowledge_source(
    payload: KnowledgeSourceCreate,
    service: Annotated[KnowledgeSourceService, Depends(get_knowledge_source_service)],
) -> KnowledgeSourceResponse:
    """
    Create a new knowledge source. Returns:
    - 201 on success
    - 400 if the Vault path does not exist or is inaccessible
    - 409 if a source with the same connector_type + scope already exists
    - 422 if the request payload fails schema validation
    """
    return await service.create(payload)


@router.get(
    "",
    response_model=list[KnowledgeSourceResponse],
    summary="List all registered knowledge sources",
)
async def list_knowledge_sources(
    service: Annotated[KnowledgeSourceService, Depends(get_knowledge_source_service)],
) -> list[KnowledgeSourceResponse]:
    """Return all sources with current status, last sync timestamp, and document count."""
    return await service.list_all()


class ToggleStatusRequest(BaseModel):
    active: bool


@router.patch(
    "/{source_id}/status",
    response_model=KnowledgeSourceResponse,
    summary="Toggle a knowledge source active or inactive",
)
async def toggle_knowledge_source_status(
    source_id: UUID,
    body: ToggleStatusRequest,
    service: Annotated[KnowledgeSourceService, Depends(get_knowledge_source_service)],
) -> KnowledgeSourceResponse:
    """
    Set ``active=true`` to re-enable a source, ``active=false`` to disable it.
    Disabling does not delete the source or its indexed documents.
    Returns 404 if the source_id does not exist.
    """
    return await service.toggle_active(source_id, body.active)


# ---------------------------------------------------------------------------
# Sync endpoints (TASK-US026-04)
# ---------------------------------------------------------------------------

class SyncTriggerResponse(BaseModel):
    job_id:  UUID
    message: str = "Sync job queued"


async def _run_sync_background(source_id: UUID, app_state: object) -> None:
    """Background coroutine: opens its own session to isolate from request lifecycle."""
    async with primary_session_factory()() as session:
        executor = SyncJobExecutor(
            session=session,
            registry=app_state.connector_registry,  # type: ignore[attr-defined]
        )
        await executor.run(source_id=source_id, is_full_sync=True)


@router.post(
    "/{source_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SyncTriggerResponse,
    summary="Trigger an on-demand full sync for a knowledge source",
)
async def trigger_sync(
    source_id: UUID,
    request: Request,
    service: Annotated[KnowledgeSourceService, Depends(get_knowledge_source_service)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SyncTriggerResponse:
    """
    Queue an on-demand full sync. Returns 202 immediately with the sync job ID.
    The caller may poll GET /{source_id}/sync/{job_id} to check job status.
    Returns 404 if source_id does not exist.
    """
    source = await service._repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge source {source_id} not found",
        )

    job_repo = SyncJobRepository(session)
    job = await job_repo.create(source_id=source_id, attempt_number=1, is_full_sync=True)
    await session.commit()

    asyncio.create_task(
        _run_sync_background(source_id, request.app.state),
        name=f"on_demand_sync_{source_id}",
    )

    return SyncTriggerResponse(job_id=job.id)


@router.get(
    "/{source_id}/sync/{job_id}",
    response_model=SyncJobResponse,
    summary="Get the status of a sync job",
)
async def get_sync_job(
    source_id: UUID,
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SyncJobResponse:
    """
    Return current status of a sync job. Poll until status is 'succeeded' or 'failed'.
    Returns 404 if the job does not exist or does not belong to the given source.
    """
    job_repo = SyncJobRepository(session)
    job = await job_repo.get(job_id)
    if job is None or job.source_id != source_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync job {job_id} not found",
        )
    return SyncJobResponse.model_validate(job)
