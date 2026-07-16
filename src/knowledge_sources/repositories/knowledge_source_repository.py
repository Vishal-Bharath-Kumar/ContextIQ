"""KnowledgeSourceRepository — raw async PostgreSQL CRUD for knowledge_sources table.

TASK-US025-03: provides the data-access layer consumed by KnowledgeSourceService.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.schemas.knowledge_source import (
    KnowledgeSourceCreate,
    SourceStatus,
)


class KnowledgeSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, source_id: UUID) -> KnowledgeSourceRecord | None:
        result = await self._session.execute(
            select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.id == source_id)
        )
        return result.scalar_one_or_none()

    async def get_by_connector_and_scope(
        self, connector_type: str, scope: str
    ) -> KnowledgeSourceRecord | None:
        result = await self._session.execute(
            select(KnowledgeSourceRecord).where(
                KnowledgeSourceRecord.connector_type == connector_type,
                KnowledgeSourceRecord.scope == scope,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, payload: KnowledgeSourceCreate) -> KnowledgeSourceRecord:
        record = KnowledgeSourceRecord(
            connector_type=payload.connector_type,
            credentials_vault_path=payload.credentials_vault_path,
            scope=payload.scope,
            sync_schedule=payload.sync_schedule,
            token_budget_weight=payload.token_budget_weight,
            status=SourceStatus.ACTIVE,
            is_active=True,
        )
        self._session.add(record)
        await self._session.flush()  # populate DB-generated id/timestamps
        return record

    async def list_all(self) -> list[KnowledgeSourceRecord]:
        result = await self._session.execute(
            select(KnowledgeSourceRecord).order_by(
                KnowledgeSourceRecord.created_at.desc()
            )
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[KnowledgeSourceRecord]:
        result = await self._session.execute(
            select(KnowledgeSourceRecord).where(
                KnowledgeSourceRecord.is_active == True  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def set_active(
        self, source_id: UUID, is_active: bool
    ) -> KnowledgeSourceRecord | None:
        record = await self.get_by_id(source_id)
        if record is None:
            return None
        record.is_active = is_active
        record.status = SourceStatus.ACTIVE if is_active else SourceStatus.INACTIVE
        await self._session.flush()
        return record
