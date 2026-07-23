"""SyncJobRepository — async CRUD for the `sync_jobs` table — TASK-US026-01.

Provides lifecycle management for sync job records linked to a KnowledgeSource.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_sources.models.sync_job import SyncJobRecord, SyncJobStatus


class SyncJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        source_id: UUID,
        attempt_number: int = 1,
        is_full_sync: bool = False,
    ) -> SyncJobRecord:
        record = SyncJobRecord(
            source_id=source_id,
            status=SyncJobStatus.RUNNING,
            attempt_number=attempt_number,
            is_full_sync=is_full_sync,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def mark_succeeded(
        self,
        job_id: UUID,
        items_processed: int,
        items_failed: int,
        duration_s: float,
    ) -> None:
        record = await self._get(job_id)
        if record:
            record.status = SyncJobStatus.SUCCEEDED
            record.completed_at = datetime.utcnow()
            record.duration_s = duration_s
            record.items_processed = items_processed
            record.items_failed = items_failed
            await self._session.flush()

    async def mark_failed(
        self, job_id: UUID, error_message: str, duration_s: float
    ) -> None:
        record = await self._get(job_id)
        if record:
            record.status = SyncJobStatus.FAILED
            record.completed_at = datetime.utcnow()
            record.duration_s = duration_s
            record.error_message = error_message[:2000]
            await self._session.flush()

    async def get(self, job_id: UUID) -> SyncJobRecord | None:
        return await self._get(job_id)

    async def list_by_source(
        self, source_id: UUID, limit: int = 10
    ) -> list[SyncJobRecord]:
        result = await self._session.execute(
            select(SyncJobRecord)
            .where(SyncJobRecord.source_id == source_id)
            .order_by(SyncJobRecord.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _get(self, job_id: UUID) -> SyncJobRecord | None:
        result = await self._session.execute(
            select(SyncJobRecord).where(SyncJobRecord.id == job_id)
        )
        return result.scalar_one_or_none()
