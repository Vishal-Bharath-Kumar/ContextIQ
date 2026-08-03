"""Knowledge Source Admin API routes — TASK-US025-04 / TASK-US026-04 / TASK-US039-04.

Registers:
  POST  /v1/knowledge-sources
  GET   /v1/knowledge-sources
  PATCH /v1/knowledge-sources/{source_id}/status
  POST  /v1/knowledge-sources/{source_id}/health-check
  POST  /v1/knowledge-sources/{source_id}/sync
  GET   /v1/knowledge-sources/{source_id}/sync/{job_id}

All routes require admin JWT.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import JWTClaimsDep, require_admin
from src.data.database import primary_session_factory
from src.data.dependencies import get_db
from src.knowledge_sources.dependencies import get_knowledge_source_service
from src.knowledge_sources.repositories.audit_repository import AuditRepository
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository
from src.knowledge_sources.schemas.connector_audit import (
    AuditEntry,
    AuditEventType,
    HealthCheckResponse,
)
from src.knowledge_sources.schemas.knowledge_source import (
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
)
from src.knowledge_sources.schemas.sync_job import SyncJobResponse
from src.knowledge_sources.services.health_check_service import HealthCheckService
from src.knowledge_sources.services.knowledge_source_service import KnowledgeSourceService
from src.knowledge_sources.sync.executor import SyncJobExecutor
from src.events.producer import get_kafka_producer

router = APIRouter(
    prefix="/v1/knowledge-sources",
    tags=["Knowledge Sources"],
    dependencies=[Depends(require_admin)],
)

_log = logging.getLogger(__name__)


async def get_audit_repo(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuditRepository:
    return AuditRepository(session)


async def _emit_initial_index_event(source_id: UUID) -> None:
    """Emit a synthetic synced event so indexing service performs first snapshot.

    We delegate indexing to the indexing service runtime (consumer on
    ``knowledge.source.synced``) instead of running embedding/indexing inside
    the API process.
    """
    try:
        producer = await get_kafka_producer()
        event = {
            "event_type": "knowledge_source_synced",
            "source_id": str(source_id),
            "tenant_id": "default",
            "job_id": str(uuid4()),
            "items_processed": 0,
            "synced_at": datetime.now(tz=UTC).isoformat(),
        }
        metadata = await producer.send_and_wait(
            "knowledge.source.synced",
            value=json.dumps(event).encode(),
        )
        print(f"✓ KAFKA_PUBLISH_SUCCESS: topic={metadata.topic} partition={metadata.partition} offset={metadata.offset} timestamp={metadata.timestamp} source_id={source_id}")
        _log.warning(
            "initial_index_event_emitted",
            extra={
                "source_id": str(source_id),
                "topic": metadata.topic,
                "partition": metadata.partition,
                "offset": metadata.offset,
                "timestamp": metadata.timestamp,
            },
        )
    except Exception as e:
        print(f"✗ KAFKA_PUBLISH_FAILED: source_id={source_id} error={type(e).__name__}: {e}")
        _log.exception(
            "initial_index_event_failed", extra={"source_id": str(source_id)}
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
    session: Annotated[AsyncSession, Depends(get_db)],
    audit_repo: Annotated[AuditRepository, Depends(get_audit_repo)],
    claims: JWTClaimsDep,
) -> KnowledgeSourceResponse:
    """
    Create a new knowledge source. Returns:
    - 201 on success
    - 400 if the Vault path does not exist or is inaccessible
    - 409 if a source with the same connector_type + scope already exists
    - 422 if the request payload fails schema validation
    """
    result = await service.create(payload)
    await audit_repo.log(
        AuditEntry(
            connector_id=result.id,
            event_type=AuditEventType.CREATED,
            actor_user_id=claims.sub,
            detail=f"connector_type={result.connector_type} scope={result.scope}",
        )
    )
    await session.commit()

    # Emit one best-effort initial indexing trigger so newly created
    # connectors surface indexed document counts in the UI without manual steps.
    await _emit_initial_index_event(result.id)
    return result


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
    session: Annotated[AsyncSession, Depends(get_db)],
    audit_repo: Annotated[AuditRepository, Depends(get_audit_repo)],
    claims: JWTClaimsDep,
) -> KnowledgeSourceResponse:
    """
    Set ``active=true`` to re-enable a source, ``active=false`` to disable it.
    Disabling does not delete the source or its indexed documents.
    Returns 404 if the source_id does not exist.
    """
    result = await service.toggle_active(source_id, body.active)
    await audit_repo.log(
        AuditEntry(
            connector_id=source_id,
            event_type=AuditEventType.STATUS_CHANGED,
            actor_user_id=claims.sub,
            detail=f"status: {'active' if body.active else 'inactive'}",
        )
    )
    await session.commit()
    return result


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete a knowledge source",
)
async def delete_knowledge_source(
    source_id: UUID,
    service: Annotated[KnowledgeSourceService, Depends(get_knowledge_source_service)],
) -> None:
    """
    Permanently delete a knowledge source. Sync-job history and connector
    audit-log entries cascade-delete with it. Already-indexed chunks/vectors
    in Qdrant/OpenSearch/the chunk index are NOT deleted (known follow-up).
    Returns 204 on success, 404 if source_id does not exist.
    """
    await service.delete(source_id)


@router.post(
    "/{source_id}/health-check",
    response_model=HealthCheckResponse,
    summary="Test live connectivity for a connector",
)
async def health_check_connector(
    source_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    audit_repo: Annotated[AuditRepository, Depends(get_audit_repo)],
    claims: JWTClaimsDep,
) -> HealthCheckResponse:
    """
    Run a live ``health_check()`` probe against the connector implementation.
    Returns ``ok=False`` (HTTP 200) on connector error — never raises for
    connector-side failures. Returns 404 if source_id does not exist and 501
    if the connector type has no implementation.
    """
    svc = HealthCheckService(session)
    result = await svc.run(source_id)
    await audit_repo.log(
        AuditEntry(
            connector_id=source_id,
            event_type=AuditEventType.HEALTH_CHECKED,
            actor_user_id=claims.sub,
            detail=f"ok={result.ok} latency_ms={result.latency_ms}",
        )
    )
    await session.commit()
    return result


# ---------------------------------------------------------------------------
# Sync endpoints (TASK-US026-04)
# ---------------------------------------------------------------------------

class SyncTriggerResponse(BaseModel):
    job_id:  UUID
    message: str = "Sync job queued"


async def _run_sync_background(source_id: UUID, job_id: UUID, app_state: object) -> None:
    """Background coroutine: opens its own session to isolate from request lifecycle."""
    async with primary_session_factory()() as session:
        executor = SyncJobExecutor(
            session=session,
            registry=app_state.connector_registry,  # type: ignore[attr-defined]
        )
        try:
            await executor.run_existing_job(
                source_id=source_id,
                job_id=job_id,
                is_full_sync=True,
            )
        except Exception:
            _log.exception(
                "on_demand_sync_failed",
                extra={"source_id": str(source_id), "job_id": str(job_id)},
            )


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
        _run_sync_background(source_id, job.id, request.app.state),
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
