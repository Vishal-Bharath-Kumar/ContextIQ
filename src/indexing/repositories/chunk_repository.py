"""ChunkRepository — async PostgreSQL data-access for the chunk_index table.

TASK-US027-01: provides idempotent upsert, document-scoped lookup, and
deletion used by the EP-008 indexing pipeline and the stale-embedding
deletion path (AC-7).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.indexing.models.chunk import ChunkRecord
from src.indexing.schemas.chunk import ChunkMetadata


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_batch(self, chunks: list[ChunkMetadata]) -> None:
        """INSERT … ON CONFLICT (chunk_id) DO UPDATE — idempotent re-indexing."""
        stmt = (
            insert(ChunkRecord)
            .values([c.model_dump() for c in chunks])
            .on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={
                    "embedding_model": insert(ChunkRecord).excluded.embedding_model,
                    "token_count": insert(ChunkRecord).excluded.token_count,
                    "indexed_at": insert(ChunkRecord).excluded.indexed_at,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def list_by_document(self, document_id: str) -> list[ChunkRecord]:
        result = await self._session.execute(
            select(ChunkRecord).where(ChunkRecord.document_id == document_id)
        )
        return list(result.scalars().all())

    async def delete_by_document(self, document_id: str) -> int:
        result = await self._session.execute(
            delete(ChunkRecord).where(ChunkRecord.document_id == document_id)
        )
        await self._session.commit()
        return result.rowcount  # type: ignore[return-value]

    async def delete_by_source(self, source_id: UUID) -> int:
        result = await self._session.execute(
            delete(ChunkRecord).where(ChunkRecord.source_id == source_id)
        )
        await self._session.commit()
        return result.rowcount  # type: ignore[return-value]
