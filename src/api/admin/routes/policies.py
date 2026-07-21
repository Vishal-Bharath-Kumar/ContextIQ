from __future__ import annotations

import logging
import os
import uuid
from itertools import groupby
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.dependencies import require_admin_role
from src.data.dependencies import get_db
from src.gateway.schemas.auth_types import JWTClaims
from src.governance.policy.models import PolicyRecord
from src.governance.policy.repository import PolicyNotFoundError, PolicyRepository
from src.governance.policy.schemas import (
    ActivateResponse,
    PolicyCreate,
    PolicyGroupSummary,
    PolicyStatus,
    PolicyVersion,
    RegoValidateRequest,
    RegoValidateResponse,
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
# Read-model mapping helpers                                          #
# ------------------------------------------------------------------ #


def _record_to_version(record: PolicyRecord) -> PolicyVersion:
    return PolicyVersion(
        id=record.id,
        policy_group=record.policy_group,
        version=record.version,
        description=record.description,
        rego_body=record.rego_body,
        status=PolicyStatus(record.status),
        author=record.author,
        activated_at=record.activated_at,
        created_at=record.created_at,
    )


def _group_to_summary(versions: list[PolicyRecord]) -> PolicyGroupSummary:
    """Fold a policy_group's version rows (already newest-first) into a summary."""
    active = next((v for v in versions if v.status == PolicyStatus.ACTIVE), None)
    latest = versions[0]
    return PolicyGroupSummary(
        id=latest.id,
        name=latest.policy_group,
        active_version=active.version if active else None,
        versions=[_record_to_version(v) for v in versions],
        latest_author=latest.author,
        activated_at=active.activated_at if active else None,
    )


# ------------------------------------------------------------------ #
# GET /v1/policies — list all policy groups (AC-2)                   #
# ------------------------------------------------------------------ #


@router.get(
    "",
    response_model=list[PolicyGroupSummary],
    summary="List every policy group with all of its versions.",
)
async def list_policies(
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PolicyGroupSummary]:
    repo = PolicyRepository(session)
    records = await repo.list_all()
    # groupby requires consecutive matching keys — list_all() orders by
    # created_at desc across ALL groups, so re-sort by policy_group first
    # (stable sort preserves the existing created_at-desc order within each group).
    records = sorted(records, key=lambda r: r.policy_group)
    groups = [
        _group_to_summary(list(rows))
        for _, rows in groupby(records, key=lambda r: r.policy_group)
    ]
    return sorted(groups, key=lambda g: g.name)


# ------------------------------------------------------------------ #
# POST /v1/policies/validate — validate Rego without persisting (AC-6)#
# ------------------------------------------------------------------ #


@router.post(
    "/validate",
    response_model=RegoValidateResponse,
    summary="Validate Rego source against OPA without persisting it.",
)
async def validate_policy(
    body: RegoValidateRequest,
    claims: AdminClaims,
) -> RegoValidateResponse:
    validator = RegoValidator(client=httpx.AsyncClient(), opa_base=_OPA_BASE_URL)
    result = await validator.validate("_ad_hoc_validation", body.rego_body)
    return RegoValidateResponse(valid=result.is_valid, errors=result.errors)


# ------------------------------------------------------------------ #
# GET /v1/policies/{id} — single policy group detail (AC-2)          #
# ------------------------------------------------------------------ #


@router.get(
    "/{policy_id}",
    response_model=PolicyGroupSummary,
    summary="Fetch one policy group (resolved via any of its version IDs).",
)
async def get_policy_detail(
    policy_id: uuid.UUID,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyGroupSummary:
    repo = PolicyRepository(session)
    record = await repo.get_by_id(policy_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        )
    versions = await repo.list_versions(record.policy_group)
    return _group_to_summary(list(versions))


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
