# TASK-US033-04 — Admin API Routes (`POST /v1/policies`, `POST /{id}/activate`, `POST /{id}/rollback`)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US033-04 |
| User Story | US-033 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Expose the three policy-lifecycle endpoints on the Admin API FastAPI router. Each endpoint is guarded by the existing JWT middleware; the caller must hold the `admin` role. Endpoints delegate all business logic to `PolicyService`. `RegoValidationError` maps to HTTP 422 (AC-6). `PolicyNotFoundError` / `PolicyVersionNotFoundError` maps to HTTP 404. An `IntegrityError` (duplicate `policy_group+version`) maps to HTTP 409.

## Implementation Details

**Technology:** Python 3.11+, FastAPI, SQLAlchemy 2.x async (`async_sessionmaker`), httpx, Pydantic v2

**File locations:**
- `src/api/admin/routes/policies.py` — FastAPI router
- `src/api/admin/dependencies.py` — `require_admin_role` dependency (shared with other admin routes)
- `src/api/admin/router.py` — include the new router (extend existing file)
- `tests/api/test_policy_routes.py`

---

### Dependency: `require_admin_role`

```python
# src/api/admin/dependencies.py
from fastapi import Depends, HTTPException, status
from src.auth.jwt import decode_jwt_claims   # existing JWT decoder


def require_admin_role(
    claims: dict = Depends(decode_jwt_claims),
) -> dict:
    """
    Raises HTTP 403 if the JWT does not contain the 'admin' role.
    Returns the full claims dict to allow downstream use of `sub`.
    """
    roles: list[str] = (
        claims.get("roles")
        or claims.get("realm_access", {}).get("roles", [])
    )
    if "admin" not in roles:
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "Admin role required.",
        )
    return claims
```

---

### Policy router

```python
# src/api/admin/routes/policies.py
from __future__ import annotations
import uuid
import logging
from typing import Annotated

from fastapi             import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc      import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session      import get_async_session                 # existing session factory
from src.governance.policy.repository import (
    PolicyRepository, PolicyNotFoundError,
)
from src.governance.policy.service    import (
    PolicyService,
    PolicyVersionNotFoundError,
    PolicyAlreadyActiveError,
)
from src.governance.policy.validator  import RegoValidator, RegoValidationError
from src.governance.policy.schemas    import (
    PolicyCreate, PolicyVersion, ActivateResponse, RollbackResponse,
)
from src.api.admin.dependencies        import require_admin_role
from src.config                        import settings   # existing pydantic-settings object

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/policies", tags=["Admin — Policies"])

AdminClaims = Annotated[dict, Depends(require_admin_role)]


def _build_service(session: AsyncSession) -> PolicyService:
    """Construct a PolicyService scoped to the current request session."""
    import httpx
    repo      = PolicyRepository(session)
    validator = RegoValidator(
        client   = httpx.AsyncClient(),
        opa_base = settings.opa_base_url,
    )
    opa_client = httpx.AsyncClient()
    return PolicyService(
        repository = repo,
        validator  = validator,
        opa_client = opa_client,
        opa_base   = settings.opa_base_url,
    )


# ------------------------------------------------------------------ #
# POST /v1/policies — AC-1                                           #
# ------------------------------------------------------------------ #

@router.post(
    "",
    response_model = PolicyVersion,
    status_code    = status.HTTP_201_CREATED,
    summary        = "Create a new governance policy version.",
)
async def create_policy(
    payload:  PolicyCreate,
    claims:   AdminClaims,
    session:  AsyncSession = Depends(get_async_session),
) -> PolicyVersion:
    """
    AC-1: Accept a Rego policy body with `name`, `description`, and `version`.
    The `sub` claim is stored as `author` (AC-5).
    """
    svc = _build_service(session)
    try:
        result = await svc.create(payload, author=claims["sub"])
        await session.commit()
        return result
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code = status.HTTP_409_CONFLICT,
            detail      = (
                f"Policy '{payload.name}' version '{payload.version}' already exists."
            ),
        )


# ------------------------------------------------------------------ #
# POST /v1/policies/{id}/activate — AC-3, AC-6                       #
# ------------------------------------------------------------------ #

@router.post(
    "/{policy_id}/activate",
    response_model = ActivateResponse,
    summary        = "Activate a policy version and push it to OPA.",
)
async def activate_policy(
    policy_id: uuid.UUID,
    claims:    AdminClaims,
    session:   AsyncSession = Depends(get_async_session),
) -> ActivateResponse:
    """
    AC-3: Promotes the specified version to active and triggers OPA bundle refresh.
    AC-6: Returns HTTP 422 with OPA parse error if the Rego is syntactically invalid.
    """
    svc = _build_service(session)
    try:
        result = await svc.activate(policy_id=policy_id)
        await session.commit()
        return result
    except PolicyNotFoundError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Policy {policy_id} not found.")
    except PolicyAlreadyActiveError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except RegoValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail      = {
                "message": "Rego policy failed syntax validation.",
                "errors":  exc.errors,
            },
        )


# ------------------------------------------------------------------ #
# POST /v1/policies/{id}/rollback?version=N — AC-4                   #
# ------------------------------------------------------------------ #

@router.post(
    "/{policy_id}/rollback",
    response_model = RollbackResponse,
    summary        = "Roll back to a prior policy version.",
)
async def rollback_policy(
    policy_id:      uuid.UUID,
    version:        str = Query(..., description="Target version string to restore."),
    claims:         AdminClaims = Depends(require_admin_role),
    session:        AsyncSession = Depends(get_async_session),
) -> RollbackResponse:
    """
    AC-4: Restores `version` to active status within the policy group.
    The policy group is resolved from the policy_id record.
    """
    svc = _build_service(session)
    # Resolve the policy_group from the record identified by policy_id
    repo   = PolicyRepository(session)
    record = await repo.get_by_id(policy_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Policy {policy_id} not found.")
    try:
        result = await svc.rollback(
            policy_group   = record.policy_group,
            target_version = version,
        )
        await session.commit()
        return result
    except PolicyVersionNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RegoValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail      = {
                "message": "Rego policy for rollback target failed syntax validation.",
                "errors":  exc.errors,
            },
        )
```

---

### Register on the admin router

```python
# src/api/admin/router.py — extend only; do NOT replace existing includes
from src.api.admin.routes.policies import router as policy_router

admin_router.include_router(policy_router)
```

---

### OpenAPI annotations (summary of all three endpoints)

| Method | Path | Status Codes | Description |
|---|---|---|---|
| `POST` | `/v1/policies` | 201, 409 | Create new policy version |
| `POST` | `/v1/policies/{id}/activate` | 200, 404, 409, 422 | Activate + push to OPA |
| `POST` | `/v1/policies/{id}/rollback?version=N` | 200, 404, 422 | Restore prior version |

## Acceptance Criteria

- [ ] `POST /v1/policies` returns 201 with full `PolicyVersion` body; `author` equals the JWT `sub` claim (AC-1, AC-5)
- [ ] `POST /v1/policies` returns 409 when the same `(name, version)` pair already exists (AC-2)
- [ ] `POST /v1/policies/{id}/activate` returns 200 with `ActivateResponse.bundle_push_ok=true` when OPA accepts the Rego (AC-3)
- [ ] `POST /v1/policies/{id}/activate` returns 422 with `errors` list when OPA rejects the Rego (AC-6)
- [ ] `POST /v1/policies/{id}/rollback?version=N` returns 404 when `version` does not exist (AC-4)
- [ ] All three endpoints return 403 when the caller lacks the `admin` role

## Dependencies

- TASK-US033-01 (`PolicyCreate`, `PolicyVersion`, `ActivateResponse`, `RollbackResponse`)
- TASK-US033-02 (`PolicyRepository`, `RegoValidator`, `RegoValidationError`, `PolicyNotFoundError`)
- TASK-US033-03 (`PolicyService`, `PolicyVersionNotFoundError`, `PolicyAlreadyActiveError`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
