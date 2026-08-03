# TASK-US035-02 — Replay API Routes (`GET /v1/traces`, `/{id}`, `/{id}/export`) and RBAC Guard

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US035-02 |
| User Story | US-035 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the three Replay Explorer FastAPI endpoints, secured with a `require_auditor_or_admin` dependency that enforces the `AUDITOR` or `ADMIN` JWT role check (AC-4). `GET /v1/traces` powers the searchable list (AC-1); `GET /v1/traces/{request_id}` returns the full detail view (AC-2, AC-3); `GET /v1/traces/{request_id}/export` streams the raw JSON as a file download (AC-6). All three must respond within 2 s for traces up to 1 year old (AC-5), satisfied by `TraceDetailService`'s Redis caching layer.

## Implementation Details

**Technology:** Python 3.11+, FastAPI, `StreamingResponse`, SQLAlchemy 2.x async, `redis.asyncio`

**File locations:**
- `src/api/admin/routes/replay.py` — FastAPI router
- `src/api/admin/dependencies.py` — extend with `require_auditor_or_admin` (add to existing file)
- `src/api/admin/router.py` — include `replay_router` (extend existing file)
- `tests/api/test_replay_routes.py`

---

### RBAC dependency

```python
# src/api/admin/dependencies.py  (add to existing file — do NOT replace require_admin_role)
from fastapi import Depends, HTTPException, status
from src.auth.jwt import decode_jwt_claims   # existing JWT decoder

_REPLAY_ALLOWED_ROLES = {"auditor", "admin", "AUDITOR", "ADMIN"}


def require_auditor_or_admin(
    claims: dict = Depends(decode_jwt_claims),
) -> dict:
    """
    AC-4: Raises HTTP 403 if the decoded JWT does not contain 'AUDITOR' or 'ADMIN'.
    Case-insensitive comparison to accommodate Keycloak realm role casing.
    Returns the claims dict for downstream use (e.g. tenant_id extraction).
    """
    roles: list[str] = (
        claims.get("roles")
        or claims.get("realm_access", {}).get("roles", [])
    )
    if not _REPLAY_ALLOWED_ROLES.intersection(set(roles)):
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "AUDITOR or ADMIN role required to access execution traces.",
        )
    return claims
```

---

### Replay router

```python
# src/api/admin/routes/replay.py
from __future__ import annotations
import logging
from typing import Annotated
from uuid   import UUID

from fastapi           import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session              import get_async_session         # existing
from src.cache.client            import get_redis_client          # existing
from src.audit.replay.service    import (
    TraceDetailService, TraceNotFoundInIndexError,
)
from src.audit.trace.repository  import TraceIndexRepository, TraceSearchQuery
from src.audit.trace.object_store import TraceObjectStore
from src.audit.replay.schemas    import TraceListResponse, TraceDetailResponse
from src.api.admin.dependencies  import require_auditor_or_admin
from src.config                  import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/traces", tags=["Admin — Replay Explorer"])

AuditorClaims = Annotated[dict, Depends(require_auditor_or_admin)]


def _build_service(session: AsyncSession, redis) -> TraceDetailService:
    repo         = TraceIndexRepository(session)
    object_store = TraceObjectStore()
    return TraceDetailService(
        index_repo   = repo,
        object_store = object_store,
        cache        = redis,
    )


# ------------------------------------------------------------------ #
# GET /v1/traces — AC-1, AC-4, AC-5                                  #
# ------------------------------------------------------------------ #

@router.get(
    "",
    response_model = TraceListResponse,
    summary        = "Search execution traces (Replay Explorer list view).",
)
async def search_traces(
    claims:   AuditorClaims,
    session:  AsyncSession = Depends(get_async_session),
    redis     = Depends(get_redis_client),
    # AC-1 search parameters
    user_id:            str | None = Query(None, description="Filter by user subject claim."),
    intent:             str | None = Query(None, description="Filter by intent type."),
    model_selected:     str | None = Query(None, description="Filter by model name."),
    governance_blocked: bool | None = Query(None, description="Filter by governance block outcome."),
    from_ts:            str | None = Query(None, alias="from",
                                           description="ISO-8601 start timestamp (inclusive)."),
    to_ts:              str | None = Query(None, alias="to",
                                           description="ISO-8601 end timestamp (inclusive)."),
    limit:  int = Query(50,  ge=1, le=500),
    offset: int = Query(0,   ge=0),
) -> TraceListResponse:
    """
    AC-1: Searchable by user_id, date range, intent type, model used, governance decision.
    AC-4: 403 if caller lacks AUDITOR or ADMIN role.
    AC-5: Served from PostgreSQL index — sub-second for recent traces.
    """
    from datetime import datetime, timezone

    query = TraceSearchQuery(
        user_id            = user_id,
        intent             = intent,
        model_selected     = model_selected,
        governance_blocked = governance_blocked,
        from_timestamp     = datetime.fromisoformat(from_ts) if from_ts else None,
        to_timestamp       = datetime.fromisoformat(to_ts)   if to_ts   else None,
        limit              = limit,
        offset             = offset,
    )
    svc       = _build_service(session, redis)
    tenant_id = claims.get("tenant_id") or claims.get("tid") or "default"
    return await svc.search(tenant_id, query)


# ------------------------------------------------------------------ #
# GET /v1/traces/{request_id} — AC-2, AC-3, AC-5                     #
# ------------------------------------------------------------------ #

@router.get(
    "/{request_id}",
    response_model = TraceDetailResponse,
    summary        = "Retrieve full execution trace detail.",
)
async def get_trace_detail(
    request_id: UUID,
    claims:     AuditorClaims,
    session:    AsyncSession = Depends(get_async_session),
    redis       = Depends(get_redis_client),
) -> TraceDetailResponse:
    """
    AC-2: Returns a step-by-step pipeline timeline (TraceDetailResponse.timeline).
    AC-3: Renders all six required detail fields.
    AC-5: Redis cache satisfies 2 s SLA for traces up to 1 year old.
    """
    svc       = _build_service(session, redis)
    tenant_id = claims.get("tenant_id") or claims.get("tid") or "default"
    try:
        return await svc.get_detail(tenant_id, request_id)
    except TraceNotFoundInIndexError:
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail      = f"Execution trace {request_id} not found.",
        )


# ------------------------------------------------------------------ #
# GET /v1/traces/{request_id}/export — AC-6                          #
# ------------------------------------------------------------------ #

@router.get(
    "/{request_id}/export",
    summary = "Download full execution trace as a JSON file.",
    response_class = StreamingResponse,
)
async def export_trace(
    request_id: UUID,
    claims:     AuditorClaims,
    session:    AsyncSession = Depends(get_async_session),
    redis       = Depends(get_redis_client),
) -> StreamingResponse:
    """
    AC-6: Returns the raw trace JSON as an attachment download.
    Filename: contextiq-trace-{request_id}.json
    """
    svc       = _build_service(session, redis)
    tenant_id = claims.get("tenant_id") or claims.get("tid") or "default"
    try:
        payload = await svc.get_raw_json(tenant_id, request_id)
    except TraceNotFoundInIndexError:
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail      = f"Execution trace {request_id} not found.",
        )

    filename = f"contextiq-trace-{request_id}.json"
    return StreamingResponse(
        content      = iter([payload]),
        media_type   = "application/json",
        headers      = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(payload)),
        },
    )
```

---

### Register on the admin router

```python
# src/api/admin/router.py — extend only; do NOT replace existing includes
from src.api.admin.routes.replay import router as replay_router

admin_router.include_router(replay_router)
```

---

### OpenAPI summary

| Method | Path | Status Codes | AC |
|---|---|---|---|
| `GET` | `/v1/traces` | 200, 403 | 1, 4, 5 |
| `GET` | `/v1/traces/{id}` | 200, 403, 404 | 2, 3, 5 |
| `GET` | `/v1/traces/{id}/export` | 200, 403, 404 | 6 |

## Acceptance Criteria

- [ ] `GET /v1/traces` returns 403 for a caller with only `developer` role (AC-4)
- [ ] `GET /v1/traces` returns 200 for a caller with `auditor` role (case-insensitive, AC-4)
- [ ] `GET /v1/traces` returns 200 for a caller with `admin` role (AC-4)
- [ ] `GET /v1/traces?user_id=X` returns only rows where `user_id == X` (AC-1)
- [ ] `GET /v1/traces?from=T1&to=T2` filters by timestamp range (AC-1)
- [ ] `GET /v1/traces/{id}` response body contains `timeline` with at least one step (AC-2)
- [ ] `GET /v1/traces/{id}` response body contains all six AC-3 fields
- [ ] `GET /v1/traces/{id}/export` returns `Content-Disposition: attachment` header and valid JSON body (AC-6)
- [ ] `GET /v1/traces/{id}` returns 404 for an unknown `request_id`

## Dependencies

- TASK-US034-03 (`TraceIndexRepository`, `TraceSearchQuery`)
- TASK-US035-01 (`TraceDetailService`, `TraceListResponse`, `TraceDetailResponse`, `require_auditor_or_admin`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
