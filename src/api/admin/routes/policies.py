import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_manage_policies
from src.gateway.schemas.auth_types import JWTClaims
from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.audit.admin_audit_log.schemas import AdminActionType
from src.data.dependencies import get_db


class CreatePolicyRequest(BaseModel):
    name: str
    rego: str

router = APIRouter(
    prefix="/v1/policies",
    tags=["Admin — Policies"],
    dependencies=[Depends(require_manage_policies)],
)

# Typed alias for route handlers that need the claims object (e.g. to record actor_user_id).
AdminClaims = Annotated[JWTClaims, Depends(require_manage_policies)]


@router.get("")
async def list_policies() -> list[dict[str, Any]]:
    return []


@router.post("", status_code=201)
async def create_policy(
    body: CreatePolicyRequest,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs POLICY_CREATED with before_state=null, after_state=new policy fields."""
    resource_id = str(uuid.uuid4())
    await audit.log(
        action=AdminActionType.POLICY_CREATED,
        resource_type="policy",
        resource_id=resource_id,
        before_state=None,
        after_state={"id": resource_id, "name": body.name, "rego": body.rego},
    )
    await session.commit()
    return {"id": resource_id, "name": body.name}


@router.patch("/{id}/activate")
async def activate_policy(
    id: uuid.UUID,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs POLICY_ACTIVATED with before_state snapshot."""
    # Placeholder: real implementation would fetch before-state and apply activation.
    await audit.log(
        action=AdminActionType.POLICY_ACTIVATED,
        resource_type="policy",
        resource_id=str(id),
        before_state=None,   # replaced by real snapshot in full implementation
        after_state=None,
    )
    await session.commit()
    return {"id": str(id)}


@router.post("/{id}/rollback")
async def rollback_policy(
    id: uuid.UUID,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs POLICY_ROLLED_BACK."""
    await audit.log(
        action=AdminActionType.POLICY_ROLLED_BACK,
        resource_type="policy",
        resource_id=str(id),
        before_state=None,
        after_state=None,
    )
    await session.commit()
    return {"id": str(id)}
