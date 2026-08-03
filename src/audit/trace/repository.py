"""TraceIndexRepository — async SQLAlchemy repository for execution_traces.

Upserts trace metadata into the PostgreSQL search index (AC-4) and exposes
search queries by request_id, user_id, timestamp, and intent.

Full trace JSON lives in MinIO; this module only manages the narrow search
index table that holds pointers (object_key, object_version) to the full doc.

Consumed by:
  - trace_writer_node background task (TASK-US034-04)
  - US-035 Replay Explorer API
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.trace.models import TraceRecord
from src.audit.trace.schemas import TraceIndexEntry

# ------------------------------------------------------------------ #
# Query / result DTOs                                                  #
# ------------------------------------------------------------------ #


class TraceSearchQuery(BaseModel):
    """Search filter for US-035 Replay Explorer (AC-4 columns)."""

    model_config = ConfigDict(frozen=True)

    user_id: str | None = None
    intent: str | None = None
    model_selected: str | None = None
    governance_blocked: bool | None = None
    from_timestamp: datetime | None = None
    to_timestamp: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class TraceSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TraceIndexEntry]
    total: int  # total rows matching the filter (for pagination)
    limit: int
    offset: int


# ------------------------------------------------------------------ #
# Repository                                                           #
# ------------------------------------------------------------------ #


class TraceIndexRepository:
    """
    Async repository for the execution_traces PostgreSQL search index (AC-4).

    Write strategy:
      INSERT … ON CONFLICT (request_id) DO UPDATE …
      This ensures idempotency — if the background write task is retried due to
      a transient DB error, the second attempt does not produce a duplicate row.
      It also handles the edge case where the MinIO write succeeds but the DB
      write was retried with an updated object_version.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Writes                                                               #
    # ------------------------------------------------------------------ #

    async def upsert(self, entry: TraceIndexEntry) -> None:
        """Insert or update a trace index row (AC-4).

        The full trace JSON lives in MinIO; this stores only searchable
        metadata plus the MinIO pointer (object_key, object_version).
        """
        stmt = (
            pg_insert(TraceRecord)
            .values(
                request_id=entry.request_id,
                tenant_id=entry.tenant_id,
                user_id=entry.user_id,
                timestamp=entry.timestamp,
                intent=entry.intent,
                model_selected=entry.model_selected,
                governance_blocked=entry.governance_blocked,
                opa_denied_count=entry.opa_denied_count,
                object_key=entry.object_key,
                object_version=entry.object_version,
            )
            .on_conflict_do_update(
                index_elements=["request_id"],
                set_={
                    "object_key": entry.object_key,
                    "object_version": entry.object_version,
                    "governance_blocked": entry.governance_blocked,
                    "opa_denied_count": entry.opa_denied_count,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    # ------------------------------------------------------------------ #
    # Reads (AC-4 — searchable by request_id, user_id, timestamp, intent) #
    # ------------------------------------------------------------------ #

    async def get_by_request_id(
        self, request_id: uuid.UUID
    ) -> TraceIndexEntry | None:
        """Return the trace index entry for the given request_id, or None."""
        result = await self._session.execute(
            select(TraceRecord).where(TraceRecord.request_id == request_id)
        )
        row = result.scalar_one_or_none()
        return _to_entry(row) if row else None

    async def search(
        self,
        tenant_id: str,
        query: TraceSearchQuery,
    ) -> TraceSearchResult:
        """Search traces by any combination of AC-4 filter columns.

        Supports: user_id, intent, model_selected, governance_blocked,
        from/to timestamp.  Results are ordered by timestamp DESC.
        """
        stmt = select(TraceRecord).where(TraceRecord.tenant_id == tenant_id)

        if query.user_id:
            stmt = stmt.where(TraceRecord.user_id == query.user_id)
        if query.intent:
            stmt = stmt.where(TraceRecord.intent == query.intent)
        if query.model_selected:
            stmt = stmt.where(TraceRecord.model_selected == query.model_selected)
        if query.governance_blocked is not None:
            stmt = stmt.where(
                TraceRecord.governance_blocked == query.governance_blocked
            )
        if query.from_timestamp:
            stmt = stmt.where(TraceRecord.timestamp >= query.from_timestamp)
        if query.to_timestamp:
            stmt = stmt.where(TraceRecord.timestamp <= query.to_timestamp)

        # Count total matching rows (for pagination)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        # Paginated result
        rows_result = await self._session.execute(
            stmt.order_by(TraceRecord.timestamp.desc())
            .limit(query.limit)
            .offset(query.offset)
        )
        rows = rows_result.scalars().all()
        return TraceSearchResult(
            items=[_to_entry(r) for r in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )


# ------------------------------------------------------------------ #
# Mapping helper                                                       #
# ------------------------------------------------------------------ #


def _to_entry(row: TraceRecord) -> TraceIndexEntry:
    return TraceIndexEntry(
        request_id=row.request_id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        timestamp=row.timestamp,
        intent=row.intent,
        model_selected=row.model_selected,
        governance_blocked=row.governance_blocked,
        opa_denied_count=row.opa_denied_count,
        object_key=row.object_key,
        object_version=row.object_version,
    )
