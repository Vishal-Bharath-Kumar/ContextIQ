# TASK-US026-04 — On-Demand Sync Endpoint: `POST /v1/knowledge-sources/{id}/sync`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US026-04 |
| User Story | US-026 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend / API |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Add `POST /v1/knowledge-sources/{id}/sync` (trigger on-demand full sync, returns 202 with job ID) and `GET /v1/knowledge-sources/{id}/sync/{job_id}` (poll job status) to the knowledge source router. The sync runs as a background `asyncio.Task` so the endpoint returns immediately without blocking. Satisfies US-026 AC-6.

## Implementation Details

**Technology:** Python 3.11+, FastAPI, Pydantic v2

**File locations:**
- `src/knowledge_sources/routers/knowledge_source_router.py` — extend existing router (do NOT replace)
- `src/knowledge_sources/schemas/sync_job.py` — `SyncJobResponse`
- `tests/knowledge_sources/test_sync_endpoints.py`

**`SyncJobResponse`:**

```python
# src/knowledge_sources/schemas/sync_job.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from src.knowledge_sources.models.sync_job import SyncJobStatus

class SyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:               UUID
    source_id:        UUID
    status:           SyncJobStatus
    attempt_number:   int
    is_full_sync:     bool
    started_at:       datetime
    completed_at:     datetime | None
    duration_s:       float | None
    items_processed:  int | None
    items_failed:     int | None
    error_message:    str | None
```

**New routes appended to existing router:**

```python
# src/knowledge_sources/routers/knowledge_source_router.py  — extend existing router

from src.knowledge_sources.schemas.sync_job import SyncJobResponse
from src.knowledge_sources.sync.executor    import SyncJobExecutor, SyncExecutorSettings
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository

class SyncTriggerResponse(BaseModel):
    job_id:    UUID
    message:   str = "Sync job queued"


@router.post(
    "/{source_id}/sync",
    status_code    = status.HTTP_202_ACCEPTED,
    response_model = SyncTriggerResponse,
    summary        = "Trigger an on-demand full sync for a knowledge source",
    dependencies   = [Depends(require_admin_role)],
)
async def trigger_sync(
    source_id:  UUID,
    request:    Request,
    service:    KnowledgeSourceService = Depends(get_knowledge_source_service),
    session:    AsyncSession           = Depends(get_async_session),
) -> SyncTriggerResponse:
    """
    Queue an on-demand full sync. Returns 202 immediately with the sync job ID.
    The caller may poll GET /{source_id}/sync/{job_id} to check job status.
    Returns 404 if source_id does not exist.
    """
    # Verify source exists (raises 404 via service if not)
    source = await service._repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Knowledge source {source_id} not found")

    registry = request.app.state.connector_registry
    executor = SyncJobExecutor(session=session, registry=registry)

    # Create job record synchronously (before returning 202) so the caller has a job_id
    job_repo = SyncJobRepository(session)
    job      = await job_repo.create(source_id=source_id, attempt_number=1, is_full_sync=True)
    await session.commit()

    # Dispatch sync as background task — non-blocking
    asyncio.create_task(
        executor.run(source_id=source_id, is_full_sync=True),
        name = f"on_demand_sync_{source_id}",
    )

    return SyncTriggerResponse(job_id=job.id)


@router.get(
    "/{source_id}/sync/{job_id}",
    response_model = SyncJobResponse,
    summary        = "Get the status of a sync job",
    dependencies   = [Depends(require_admin_role)],
)
async def get_sync_job(
    source_id: UUID,
    job_id:    UUID,
    session:   AsyncSession = Depends(get_async_session),
) -> SyncJobResponse:
    """
    Return current status of a sync job. Poll until `status` is 'succeeded' or 'failed'.
    Returns 404 if the job does not exist or does not belong to the given source.
    """
    job_repo = SyncJobRepository(session)
    job      = await job_repo.get(job_id)
    if job is None or job.source_id != source_id:
        raise HTTPException(status_code=404, detail=f"Sync job {job_id} not found")
    return SyncJobResponse.model_validate(job)
```

**Session and background task isolation:**

The `asyncio.create_task()` in `trigger_sync` captures `executor` which holds a reference to `session`. The FastAPI dependency-managed session is closed at the end of the request lifecycle. The background task must therefore open its own session via `session_factory`. The `executor.run()` implementation (TASK-US026-02) uses `session` passed at construction; for the on-demand path, pass `session_factory` instead of a bound session:

```python
# executor.run() called from background task uses request.app.state.db_session_factory
asyncio.create_task(
    _run_sync_background(source_id, request.app.state),
    name = f"on_demand_sync_{source_id}",
)

async def _run_sync_background(source_id: UUID, app_state) -> None:
    async with app_state.db_session_factory() as session:
        executor = SyncJobExecutor(session=session, registry=app_state.connector_registry)
        await executor.run(source_id=source_id, is_full_sync=True)
```

**HTTP summary:**

| Method | Path | Success | Errors |
|---|---|---|---|
| POST | `/v1/knowledge-sources/{id}/sync` | 202 `SyncTriggerResponse` | 404 |
| GET | `/v1/knowledge-sources/{id}/sync/{job_id}` | 200 `SyncJobResponse` | 404 |

## Acceptance Criteria

- [ ] `POST /{id}/sync` returns HTTP 202 immediately with a `job_id`
- [ ] `POST /{id}/sync` on an unknown `source_id` returns HTTP 404
- [ ] The `asyncio.create_task` is dispatched without awaiting — verified by response time < 100 ms
- [ ] `GET /{id}/sync/{job_id}` returns the current `SyncJobResponse` (status may be `running`)
- [ ] `GET /{id}/sync/{job_id}` with a `job_id` belonging to a different `source_id` returns 404
- [ ] Non-admin requests return 403

## Dependencies

- TASK-US026-01 (`SyncJobRepository`, `SyncJobResponse`)
- TASK-US026-02 (`SyncJobExecutor.run()`)
- TASK-US025-04 (existing router — routes appended here)
- TASK-US025-03 (`KnowledgeSourceRepository.get_by_id()`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `httpx.AsyncClient`; background task mocked via `patch("asyncio.create_task")`
- [ ] `mypy --strict` passes; no `ruff` lint errors
