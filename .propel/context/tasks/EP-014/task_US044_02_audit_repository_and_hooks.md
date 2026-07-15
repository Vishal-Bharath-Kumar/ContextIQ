# TASK-US044-02 — Audit Repository and FastAPI Middleware for All Mutating Routes

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US044-02 |
| User Story | US-044 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Implement `AdminAuditRepository` that writes rows to `admin_audit_log` with the SHA-256 hash chain (AC-1, AC-6). Implement `AuditContext`, a request-scoped helper injected by FastAPI `Depends` that captures the caller's `ip_address` and `actor_user_id` from `request.state.jwt_claims` and provides a `log()` convenience method. Apply `AuditContext` to every mutating Admin API route across all three domains: policies (`/v1/policies`), connectors (`/v1/knowledge-sources`), and model registry (`/v1/models`, `/v1/routing/weights`). This task replaces the per-domain audit logs added in EP-013 (US-039-04, US-040-05, US-041-05) with writes to the unified table.

## Implementation Details

**Technology:** Python 3.11+, FastAPI `Depends`, SQLAlchemy 2.x async, Pydantic v2

**File locations:**
- `src/audit/admin_audit_log/repository.py` — `AdminAuditRepository`
- `src/audit/admin_audit_log/context.py` — `AuditContext` FastAPI dependency
- `src/api/admin/routes/policies.py` — add `AuditContext` to mutating routes
- `src/knowledge_sources/routers/knowledge_source_router.py` — add `AuditContext`
- `src/model_registry/routers/model_router.py` — add `AuditContext`
- `src/model_router/routers/routing_weight_router.py` — add `AuditContext`

---

### `AdminAuditRepository`

```python
# src/audit/admin_audit_log/repository.py
from __future__ import annotations
import uuid
import logging
from datetime                     import datetime, timezone
from typing                       import Any

from sqlalchemy                   import select, func
from sqlalchemy.ext.asyncio       import AsyncSession

from src.audit.admin_audit_log.models     import AdminAuditLog
from src.audit.admin_audit_log.schemas    import AuditLogCreateRequest
from src.audit.admin_audit_log.hash_chain import (
    compute_row_hash,
    row_fields_for_hashing,
    GENESIS_PREV_HASH,
)

logger = logging.getLogger(__name__)


class AdminAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(self, request: AuditLogCreateRequest) -> AdminAuditLog:
        """
        AC-1: Append one audit entry.
        AC-6: Computes row_hash = SHA-256(prev_hash || canonical_json(row)).
        The session is NOT committed here — the calling route handler owns the transaction.
        """
        timestamp = datetime.now(timezone.utc)

        prev_hash = await self._latest_row_hash()

        fields = row_fields_for_hashing(
            action        = request.action,
            resource_type = request.resource_type,
            resource_id   = request.resource_id,
            actor_user_id = request.actor_user_id,
            ip_address    = request.ip_address,
            before_state  = request.before_state,
            after_state   = request.after_state,
            timestamp     = timestamp,
        )
        row_hash = compute_row_hash(prev_hash, fields)

        entry = AdminAuditLog(
            id            = uuid.uuid4(),
            action        = request.action,
            resource_type = request.resource_type,
            resource_id   = request.resource_id,
            actor_user_id = request.actor_user_id,
            ip_address    = request.ip_address,
            before_state  = request.before_state,
            after_state   = request.after_state,
            timestamp     = timestamp,
            row_hash      = row_hash,
        )
        self._session.add(entry)
        await self._session.flush()   # assign DB id without committing
        logger.debug(
            "audit_log.append action=%s resource=%s/%s actor=%s",
            request.action, request.resource_type, request.resource_id, request.actor_user_id,
        )
        return entry

    async def _latest_row_hash(self) -> str:
        """
        Returns the `row_hash` of the most recently inserted row,
        or GENESIS_PREV_HASH if the table is empty.
        """
        result = await self._session.execute(
            select(AdminAuditLog.row_hash)
            .order_by(AdminAuditLog.timestamp.desc(), AdminAuditLog.id.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        return latest if latest is not None else GENESIS_PREV_HASH
```

---

### `AuditContext` FastAPI dependency

```python
# src/audit/admin_audit_log/context.py
from __future__ import annotations
from typing import Any, Annotated

from fastapi             import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session                       import get_session
from src.audit.admin_audit_log.repository import AdminAuditRepository
from src.audit.admin_audit_log.schemas    import AuditLogCreateRequest, AdminActionType
from src.gateway.schemas.auth_types       import JWTClaims
from src.auth.dependencies                import decode_jwt_claims


def _extract_ip(request: Request) -> str:
    """
    Extract the caller's IP address.
    Prefers the first value of X-Forwarded-For (set by nginx Ingress)
    over the direct socket peer address.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class AuditContext:
    """
    Request-scoped helper that captures audit metadata from the incoming request
    and provides a `log()` method that writes to `AdminAuditRepository`.

    Injected via `Depends(get_audit_context)` in mutating route handlers.

    Usage in a route handler:
        @router.post("/v1/policies")
        async def create_policy(
            body:    PolicyCreateRequest,
            audit:   AuditContext = Depends(get_audit_context),
            session: AsyncSession = Depends(get_session),
        ) -> PolicyResponse:
            # snapshot before (None for creates)
            created = await policy_service.create(body, session)
            await audit.log(
                action        = AdminActionType.POLICY_CREATED,
                resource_type = "policy",
                resource_id   = str(created.id),
                before_state  = None,
                after_state   = created.model_dump(),
            )
            return created
    """

    def __init__(
        self,
        request: Request,
        claims:  JWTClaims,
        session: AsyncSession,
    ) -> None:
        self._ip         = _extract_ip(request)
        self._actor      = claims.sub
        self._repo       = AdminAuditRepository(session)

    async def log(
        self,
        *,
        action:        AdminActionType,
        resource_type: str,
        resource_id:   str,
        before_state:  dict[str, Any] | None = None,
        after_state:   dict[str, Any] | None = None,
    ) -> None:
        await self._repo.log(
            AuditLogCreateRequest(
                action        = action,
                resource_type = resource_type,
                resource_id   = resource_id,
                actor_user_id = self._actor,
                ip_address    = self._ip,
                before_state  = before_state,
                after_state   = after_state,
            )
        )


async def get_audit_context(
    request: Request,
    claims:  Annotated[JWTClaims, Depends(decode_jwt_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuditContext:
    """FastAPI dependency factory — returns a per-request `AuditContext`."""
    return AuditContext(request=request, claims=claims, session=session)
```

---

### Example: applying `AuditContext` to the policy create route

```python
# src/api/admin/routes/policies.py  (extend — excerpt showing audit hook pattern)
from src.audit.admin_audit_log.context  import AuditContext, get_audit_context
from src.audit.admin_audit_log.schemas  import AdminActionType

@router.post("/v1/policies", status_code=201)
async def create_policy(
    body:    PolicyCreateRequest,
    audit:   AuditContext         = Depends(get_audit_context),
    session: AsyncSession         = Depends(get_session),
    _claims: JWTClaims            = Depends(require_manage_policies),
) -> PolicyResponse:
    created = await _policy_service(session).create(body)
    await audit.log(
        action        = AdminActionType.POLICY_CREATED,
        resource_type = "policy",
        resource_id   = str(created.id),
        before_state  = None,
        after_state   = created.model_dump(mode="json"),
    )
    return created


@router.patch("/v1/policies/{id}/activate")
async def activate_policy(
    id:      uuid.UUID,
    audit:   AuditContext = Depends(get_audit_context),
    session: AsyncSession = Depends(get_session),
    _claims: JWTClaims    = Depends(require_manage_policies),
) -> PolicyResponse:
    before  = await _policy_service(session).get(id)
    updated = await _policy_service(session).activate(id)
    await audit.log(
        action        = AdminActionType.POLICY_ACTIVATED,
        resource_type = "policy",
        resource_id   = str(id),
        before_state  = before.model_dump(mode="json"),
        after_state   = updated.model_dump(mode="json"),
    )
    return updated
```

---

### Route coverage table

All routes below must have `audit: AuditContext = Depends(get_audit_context)` added:

| Router file | HTTP method | Path | `AdminActionType` |
|---|---|---|---|
| `policies.py` | POST | `/v1/policies` | `POLICY_CREATED` |
| `policies.py` | PATCH | `/v1/policies/{id}/activate` | `POLICY_ACTIVATED` |
| `policies.py` | POST | `/v1/policies/{id}/rollback` | `POLICY_ROLLED_BACK` |
| `knowledge_source_router.py` | POST | `/v1/knowledge-sources` | `CONNECTOR_CREATED` |
| `knowledge_source_router.py` | PATCH | `/v1/knowledge-sources/{id}` | `CONNECTOR_UPDATED` |
| `knowledge_source_router.py` | PATCH | `/v1/knowledge-sources/{id}/status` | `CONNECTOR_STATUS_CHANGED` |
| `model_router.py` | POST | `/v1/models` | `MODEL_REGISTERED` |
| `model_router.py` | PATCH | `/v1/models/{id}/status` | `MODEL_STATUS_CHANGED` |
| `routing_weight_router.py` | PUT | `/v1/routing/weights/{intent_type}` | `MODEL_WEIGHTS_UPDATED` |

## Acceptance Criteria

- [x] Every mutating route in the coverage table above logs one row to `admin_audit_log` per request (AC-1)
- [x] `before_state` is `null` for create operations; populated with the current resource snapshot for update/status operations (AC-1)
- [x] `ip_address` is populated from `X-Forwarded-For` when present, falling back to `request.client.host` (AC-1)
- [x] `actor_user_id` equals the `sub` claim from the JWT (AC-1)
- [x] `AuditContext.log()` delegates to `AdminAuditRepository.log()` which computes and stores `row_hash` (AC-6)
- [x] `_latest_row_hash()` returns `GENESIS_PREV_HASH` when the table is empty (AC-6)

## Dependencies

- TASK-US044-01 — `AdminAuditLog` ORM, `AuditLogCreateRequest`, `compute_row_hash`
- TASK-US042-02 — `decode_jwt_claims` dependency, `require_manage_policies` etc.
- EP-013 tasks — existing mutating routes that receive `AuditContext` additions

## Definition of Done

- [x] `grep -r "get_audit_context" src/api/admin/routes/ src/knowledge_sources/routers/ src/model_registry/routers/ src/model_router/routers/` returns 9 matches (one per row in the coverage table)
- [x] `mypy --strict src/audit/admin_audit_log/repository.py src/audit/admin_audit_log/context.py` passes
