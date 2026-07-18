"""PolicyAuditRepository — persistence layer for policy audit trail entries.

Provides ordered reads and append-only writes for the policy_audit_log table.
All writes use flush() so the caller's outer commit controls transaction
boundaries (AC-6).
"""
from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.governance.policy.models import PolicyAuditLog


class PolicyAuditRepository:
    """Data-access object for the ``policy_audit_log`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_policy(
        self,
        policy_id: uuid.UUID,
        limit: int = 50,
    ) -> list[PolicyAuditLog]:
        """Return the *limit* most-recent audit entries for *policy_id*, newest first."""
        result = await self._session.execute(
            select(PolicyAuditLog)
            .where(PolicyAuditLog.policy_id == policy_id)
            .order_by(desc(PolicyAuditLog.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def log(
        self,
        policy_id: uuid.UUID,
        event_type: str,
        actor_user_id: str,
        detail: str | None = None,
    ) -> None:
        """Append an audit entry and flush within the current transaction."""
        entry = PolicyAuditLog(
            policy_id=policy_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            detail=detail,
        )
        self._session.add(entry)
        await self._session.flush()
