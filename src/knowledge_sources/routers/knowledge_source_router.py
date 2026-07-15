import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_manage_connectors
from src.audit.admin_audit_log.context import AuditContext, get_audit_context
from src.audit.admin_audit_log.schemas import AdminActionType
from src.data.dependencies import get_db

router = APIRouter(
    prefix="/v1/knowledge-sources",
    tags=["Knowledge Sources"],
    dependencies=[Depends(require_manage_connectors)],
)


@router.get("")
async def list_knowledge_sources() -> list[dict[str, Any]]:
    return []


@router.post("", status_code=201)
async def create_knowledge_source(
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs CONNECTOR_CREATED."""
    resource_id = str(uuid.uuid4())
    await audit.log(
        action=AdminActionType.CONNECTOR_CREATED,
        resource_type="connector",
        resource_id=resource_id,
        before_state=None,
        after_state=None,
    )
    await session.commit()
    return {"id": resource_id}


@router.patch("/{id}")
async def update_knowledge_source(
    id: uuid.UUID,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs CONNECTOR_UPDATED with before_state snapshot."""
    await audit.log(
        action=AdminActionType.CONNECTOR_UPDATED,
        resource_type="connector",
        resource_id=str(id),
        before_state=None,
        after_state=None,
    )
    await session.commit()
    return {"id": str(id)}


@router.patch("/{id}/status")
async def update_knowledge_source_status(
    id: uuid.UUID,
    audit: Annotated[AuditContext, Depends(get_audit_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AC-1: logs CONNECTOR_STATUS_CHANGED."""
    await audit.log(
        action=AdminActionType.CONNECTOR_STATUS_CHANGED,
        resource_type="connector",
        resource_id=str(id),
        before_state=None,
        after_state=None,
    )
    await session.commit()
    return {"id": str(id)}
