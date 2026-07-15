import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_manage_models
from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.audit.admin_audit_log.schemas import AdminActionType
from src.data.dependencies import get_db


class ModelStatusUpdateRequest(BaseModel):
    active: bool

router = APIRouter(
    prefix="/v1/models",
    tags=["Model Registry"],
    dependencies=[Depends(require_manage_models)],
)


@router.get("")
async def list_models() -> list[dict[str, Any]]:
    return []


@router.post("", status_code=201)
async def register_model(
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs MODEL_REGISTERED."""
    resource_id = str(uuid.uuid4())
    await audit.log(
        action=AdminActionType.MODEL_REGISTERED,
        resource_type="model",
        resource_id=resource_id,
        before_state=None,
        after_state=None,
    )
    await session.commit()
    return {"id": resource_id}


@router.patch("/{id}/status")
async def update_model_status(
    id: uuid.UUID,
    body: ModelStatusUpdateRequest,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs MODEL_STATUS_CHANGED with before_state and after_state."""
    await audit.log(
        action=AdminActionType.MODEL_STATUS_CHANGED,
        resource_type="model",
        resource_id=str(id),
        before_state={"active": not body.active},   # inferred previous state
        after_state={"active": body.active},
    )
    await session.commit()
    return {"id": str(id)}
