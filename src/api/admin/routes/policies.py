from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.dependencies import require_admin_role
from src.data.dependencies import get_db
from src.gateway.schemas.auth_types import JWTClaims
from src.governance.policy.repository import PolicyNotFoundError, PolicyRepository
from src.governance.policy.schemas import (
    ActivateResponse,
    PolicyCreate,
    PolicyVersion,
    RollbackResponse,
)
from src.governance.policy.service import (
    PolicyAlreadyActiveError,
    PolicyService,
    PolicyVersionNotFoundError,
)
from src.governance.policy.validator import RegoValidationError, RegoValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/policies", tags=["Admin — Policies"])

AdminClaims = Annotated[JWTClaims, Depends(require_admin_role)]

_OPA_BASE_URL = os.environ.get("OPA_BASE_URL", "http://localhost:8181")


def _build_service(session: AsyncSession) -> PolicyService:
    """Construct a PolicyService scoped to the current request session."""
    repo = PolicyRepository(session)
    validator = RegoValidator(
        client=httpx.AsyncClient(),
        opa_base=_OPA_BASE_URL,
    )
    opa_client = httpx.AsyncClient()
    return PolicyService(
        repository=repo,
        validator=validator,
        opa_client=opa_client,
        opa_base=_OPA_BASE_URL,
    )


# ------------------------------------------------------------------ #
# POST /v1/policies — AC-1                                           #
# ------------------------------------------------------------------ #


@router.post(
    "",
    response_model=PolicyVersion,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new governance policy version.",
)
async def create_policy(
    payload: PolicyCreate,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyVersion:
    """
    AC-1: Accept a Rego policy body with `name`, `description`, and `version`.
    The `sub` claim is stored as `author` (AC-5).
    """
    svc = _build_service(session)
    try:
        result = await svc.create(payload, author=claims.sub)
        await session.commit()
        return result
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Policy '{payload.name}' version '{payload.version}' already exists.",
        ) from exc


# ------------------------------------------------------------------ #
# POST /v1/policies/{id}/activate — AC-3, AC-6                       #
# ------------------------------------------------------------------ #


@router.post(
    "/{policy_id}/activate",
    response_model=ActivateResponse,
    summary="Activate a policy version and push it to OPA.",
)
async def activate_policy(
    policy_id: uuid.UUID,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
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
    except PolicyNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        ) from exc
    except PolicyAlreadyActiveError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except RegoValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Rego policy failed syntax validation.",
                "errors": exc.errors,
            },
        ) from exc


# ------------------------------------------------------------------ #
# POST /v1/policies/{id}/rollback?version=N — AC-4                   #
# ------------------------------------------------------------------ #


@router.post(
    "/{policy_id}/rollback",
    response_model=RollbackResponse,
    summary="Roll back to a prior policy version.",
)
async def rollback_policy(
    policy_id: uuid.UUID,
    claims: AdminClaims,
    version: Annotated[str, Query(description="Target version string to restore.")],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RollbackResponse:
    """
    AC-4: Restores `version` to active status within the policy group.
    The policy group is resolved from the policy_id record.
    """
    svc = _build_service(session)
    repo = PolicyRepository(session)
    record = await repo.get_by_id(policy_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        )
    try:
        result = await svc.rollback(
            policy_group=record.policy_group,
            target_version=version,
        )
        await session.commit()
        return result
    except PolicyVersionNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except RegoValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Rego policy for rollback target failed syntax validation.",
                "errors": exc.errors,
            },
        ) from exc
