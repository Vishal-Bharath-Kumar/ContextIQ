"""AuditRepository — write-only log for connector mutation events — TASK-US039-04."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_sources.models.connector_audit_log import ConnectorAuditLog
from src.knowledge_sources.schemas.connector_audit import AuditEntry


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(self, entry: AuditEntry) -> None:
        """Append an audit entry within the caller's active transaction."""
        record = ConnectorAuditLog(
            connector_id=entry.connector_id,
            event_type=entry.event_type,
            actor_user_id=entry.actor_user_id,
            detail=entry.detail,
        )
        self._session.add(record)
        await self._session.flush()  # write within current transaction; commit by caller
