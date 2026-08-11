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
from src.audit.trace.object_store import TraceObjectStore
from src.data.dependencies import get_db
from src.gateway.schemas.auth_types import JWTClaims
from src.governance.policy.audit_repository import PolicyAuditRepository
from src.governance.policy.models import PolicyRecord
from src.governance.policy.repository import PolicyNotFoundError, PolicyRepository
from src.governance.policy.schemas import (
    ActivateResponse,
    PolicyAuditEntry,
    PolicyCreate,
    PolicyGroupSummary,
    PolicyPreviewRequest,
    PolicyPreviewResult,
    PolicyStatus,
    PolicyUpdate,
    PolicyVersion,
    RegoValidateRequest,
    RegoValidateResponse,
)
from src.governance.policy.preview_service import PolicyPreviewService
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
    audit_repo = PolicyAuditRepository(session)
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
        audit_repository=audit_repo,
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
# PUT /v1/policies/{id} — Update a policy version                    #
# ------------------------------------------------------------------ #


@router.put(
    "/{policy_id}",
    response_model=PolicyVersion,
    summary="Update an existing policy version (DRAFT only).",
)
async def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyVersion:
    """
    Update the description and/or rego_body of an existing policy version.
    Only DRAFT policies can be updated.
    """
    svc = _build_service(session)
    try:
        result = await svc.update(
            policy_id=policy_id,
            description=payload.description,
            rego_body=payload.rego_body,
            author=claims.sub,
        )
        await session.commit()
        return result
    except PolicyNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ------------------------------------------------------------------ #
# DELETE /v1/policies/{id} — Delete a policy version                 #
# ------------------------------------------------------------------ #


@router.delete(
    "/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a policy version (DRAFT or SUPERSEDED only).",
)
async def delete_policy(
    policy_id: uuid.UUID,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """
    Delete a policy version. Only DRAFT or SUPERSEDED policies can be deleted.
    Active policies must be deactivated first.
    """
    svc = _build_service(session)
    try:
        await svc.delete(policy_id=policy_id, author=claims.sub)
        await session.commit()
    except PolicyNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


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
        logger.error(f"Policy not found during activation: {exc}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        ) from exc
    except PolicyAlreadyActiveError as exc:
        await session.rollback()
        logger.error(f"Policy already active: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except RegoValidationError as exc:
        await session.rollback()
        logger.error(f"Rego validation failed: {exc.errors}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Rego policy failed syntax validation.",
                "errors": exc.errors,
            },
        ) from exc


# ------------------------------------------------------------------ #
# POST /v1/policies/{id}/deactivate — Deactivate active policy      #
# ------------------------------------------------------------------ #


@router.post(
    "/{policy_id}/deactivate",
    response_model=PolicyVersion,
    summary="Deactivate an active policy and remove it from OPA.",
)
async def deactivate_policy(
    policy_id: uuid.UUID,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyVersion:
    """
    Deactivate an active policy version and remove it from OPA.
    The policy status changes to SUPERSEDED.
    """
    svc = _build_service(session)
    try:
        result = await svc.deactivate(policy_id=policy_id, author=claims.sub)
        await session.commit()
        return result
    except PolicyNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ------------------------------------------------------------------ #
# POST /v1/policies/{id}/preview — AC-3 policy impact simulation     #
# ------------------------------------------------------------------ #


@router.post(
    "/{policy_id}/preview",
    response_model=PolicyPreviewResult,
    summary="Simulate a draft policy against recent execution traces.",
)
async def preview_policy(
    policy_id: uuid.UUID,
    request: PolicyPreviewRequest,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyPreviewResult:
    """
    AC-3: Temporarily push the Rego body to OPA, evaluate against the last
    100 execution traces, and return allow/deny statistics.
    The temporary policy is deleted afterward.
    """
    preview_svc = PolicyPreviewService(
        session=session,
        opa_client=httpx.AsyncClient(trust_env=False),
        opa_base=_OPA_BASE_URL,
        object_store=TraceObjectStore(),
    )
    try:
        result = await preview_svc.preview(policy_id=policy_id, request=request)
        return result
    except httpx.ConnectError as exc:
        logger.error("Failed to connect to OPA for policy preview: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPA service is not available. Policy preview requires OPA to be running.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.error("OPA returned error during policy preview: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OPA service error: {exc.response.text if exc.response else str(exc)}",
        ) from exc


# ------------------------------------------------------------------ #
# GET /v1/policies/{id}/audit — fetch policy audit trail             #
# ------------------------------------------------------------------ #


@router.get(
    "/{policy_id}/audit",
    response_model=list[PolicyAuditEntry],
    summary="Retrieve audit trail for a policy.",
)
async def get_policy_audit(
    policy_id: uuid.UUID,
    claims: AdminClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[PolicyAuditEntry]:
    """
    Return audit log entries for the specified policy, newest first.
    Defaults to last 50 entries; maximum 500.
    """
    audit_repo = PolicyAuditRepository(session)
    entries = await audit_repo.get_for_policy(policy_id, limit=limit)
    return [
        PolicyAuditEntry(
            id=e.id,
            policy_id=e.policy_id,
            event_type=e.event_type,
            actor_user_id=e.actor_user_id,
            detail=e.detail,
            created_at=e.created_at,
        )
        for e in entries
    ]
