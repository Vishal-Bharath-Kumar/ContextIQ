import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_manage_models
from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.audit.admin_audit_log.schemas import AdminActionType
from src.data.dependencies import get_db

router = APIRouter(
    prefix="/v1/routing/weights",
    tags=["Routing Weights"],
    dependencies=[Depends(require_manage_models)],
)


@router.get("")
async def list_routing_weights() -> list[dict[str, Any]]:
    return []


@router.put("/{intent_type}")
async def update_routing_weights(
    intent_type: str,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs MODEL_WEIGHTS_UPDATED."""
    await audit.log(
        action=AdminActionType.MODEL_WEIGHTS_UPDATED,
        resource_type="routing_weight",
        resource_id=intent_type,
        before_state=None,
        after_state=None,
    )
    await session.commit()
    return {"intent_type": intent_type}
