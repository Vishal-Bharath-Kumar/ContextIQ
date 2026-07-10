# TASK-US025-04 — Admin API: `POST`, `GET`, and `PATCH` Knowledge Source Endpoints

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US025-04 |
| User Story | US-025 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend / API |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Register three FastAPI routes for the Knowledge Source Admin API: `POST /v1/knowledge-sources` (create), `GET /v1/knowledge-sources` (list with status and counts), and `PATCH /v1/knowledge-sources/{id}/status` (toggle active/inactive without deletion). All endpoints require admin JWT auth and delegate to `KnowledgeSourceService`.

## Implementation Details

**Technology:** Python 3.11+, FastAPI, Pydantic v2

**File locations:**
- `src/knowledge_sources/routers/knowledge_source_router.py` — route definitions
- `src/knowledge_sources/dependencies.py` — `get_knowledge_source_service()` dependency
- `tests/knowledge_sources/test_knowledge_source_router.py` — `httpx.AsyncClient` tests

**`dependencies.py`:**

```python
# src/knowledge_sources/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session          import get_async_session
from src.knowledge_sources.services.knowledge_source_service import KnowledgeSourceService
from src.knowledge_sources.vault_validator import VaultPathValidator

async def get_knowledge_source_service(
    session: AsyncSession = Depends(get_async_session),
) -> KnowledgeSourceService:
    return KnowledgeSourceService(session=session, validator=VaultPathValidator())
```

**`knowledge_source_router.py`:**

```python
# src/knowledge_sources/routers/knowledge_source_router.py
from uuid import UUID
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from src.knowledge_sources.schemas.knowledge_source    import KnowledgeSourceCreate, KnowledgeSourceResponse
from src.knowledge_sources.services.knowledge_source_service import KnowledgeSourceService
from src.knowledge_sources.dependencies                import get_knowledge_source_service
from src.gateway.middleware.auth                       import require_admin_role

router = APIRouter(
    prefix       = "/v1/knowledge-sources",
    tags         = ["Knowledge Sources"],
    dependencies = [Depends(require_admin_role)],   # all routes require admin JWT
)


@router.post(
    "",
    status_code    = status.HTTP_201_CREATED,
    response_model = KnowledgeSourceResponse,
    summary        = "Register a new knowledge source",
)
async def create_knowledge_source(
    payload: KnowledgeSourceCreate,
    service: KnowledgeSourceService = Depends(get_knowledge_source_service),
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
    response_model = list[KnowledgeSourceResponse],
    summary        = "List all registered knowledge sources",
)
async def list_knowledge_sources(
    service: KnowledgeSourceService = Depends(get_knowledge_source_service),
) -> list[KnowledgeSourceResponse]:
    """Return all sources with current status, last sync timestamp, and document count."""
    return await service.list_all()


class ToggleStatusRequest(BaseModel):
    active: bool


@router.patch(
    "/{source_id}/status",
    response_model = KnowledgeSourceResponse,
    summary        = "Toggle a knowledge source active or inactive",
)
async def toggle_knowledge_source_status(
    source_id: UUID,
    body:      ToggleStatusRequest,
    service:   KnowledgeSourceService = Depends(get_knowledge_source_service),
) -> KnowledgeSourceResponse:
    """
    Set `active=true` to re-enable a source, `active=false` to disable it.
    Disabling does not delete the source or its indexed documents.
    Returns 404 if the source_id does not exist.
    """
    return await service.toggle_active(source_id, body.active)
```

**Router registration in app factory (extend existing, do NOT replace):**

```python
# src/gateway/main.py
from src.knowledge_sources.routers.knowledge_source_router import router as ks_router
app.include_router(ks_router)
```

**`ToggleStatusRequest` placement:**

`ToggleStatusRequest` lives in the router file rather than `schemas/` because it is a one-field request body unique to this endpoint — creating a separate schema file for it would violate the DRY principle and add unnecessary module indirection.

**HTTP response summary:**

| Method | Path | Success | Client errors |
|---|---|---|---|
| POST | `/v1/knowledge-sources` | 201 `KnowledgeSourceResponse` | 400, 409, 422 |
| GET | `/v1/knowledge-sources` | 200 `list[KnowledgeSourceResponse]` | — |
| PATCH | `/v1/knowledge-sources/{id}/status` | 200 `KnowledgeSourceResponse` | 404, 422 |

## Acceptance Criteria

- [ ] `POST /v1/knowledge-sources` with a valid payload returns HTTP 201 and a `KnowledgeSourceResponse`
- [ ] `POST /v1/knowledge-sources` with invalid Vault path returns HTTP 400 with descriptive `detail`
- [ ] `POST /v1/knowledge-sources` with duplicate `(connector_type, scope)` returns HTTP 409
- [ ] `GET /v1/knowledge-sources` returns a JSON array including `status`, `last_sync_at`, `document_count`
- [ ] `PATCH /v1/knowledge-sources/{id}/status` with `{"active": false}` sets `status="inactive"`
- [ ] `PATCH /v1/knowledge-sources/{unknown}/status` returns HTTP 404
- [ ] Non-admin requests to all three endpoints return HTTP 403

## Dependencies

- TASK-US025-01 (`KnowledgeSourceCreate`, `KnowledgeSourceResponse`)
- TASK-US025-03 (`KnowledgeSourceService`)
- TASK-US018-04 (JWT `require_admin_role` dependency pattern)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] OpenAPI schema auto-generated via FastAPI — reviewed for correct status codes
- [ ] Tests use `httpx.AsyncClient` with mocked `KnowledgeSourceService`
- [ ] `mypy --strict` passes; no `ruff` lint errors
