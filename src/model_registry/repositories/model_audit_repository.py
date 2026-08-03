"""Async repository for the model_audit_log table.

Provides a single ``log()`` method consumed by mutating route handlers
(POST /v1/models, PATCH /v1/models/{id}/status, PUT /v1/routing/weights/{intent}).

TASK-US041-05
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.model_registry.models.model_audit_log import ModelAuditLog


class ModelAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        model_id: str,
        event_type: str,
        actor_user_id: str,
        detail: str | None = None,
    ) -> None:
        """Append one audit row.  Flushes but does not commit — the caller owns the transaction."""
        entry = ModelAuditLog(
            model_id=model_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            detail=detail,
        )
        self._session.add(entry)
        await self._session.flush()
