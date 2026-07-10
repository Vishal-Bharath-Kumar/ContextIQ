# TASK-US034-03 — `TraceIndexRepository` (PostgreSQL Search Index)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US034-03 |
| User Story | US-034 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `TraceIndexRepository` — the async SQLAlchemy repository that upserts trace metadata into the `execution_traces` PostgreSQL table and exposes search queries by `request_id`, `user_id`, `timestamp`, and `intent` (AC-4). This table is intentionally narrow: it holds only the columns required for search and the `object_key`/`object_version` pointer back to the full JSON in MinIO. Consumed by the async background task in `trace_writer_node` (TASK-US034-04) and by the US-035 Replay Explorer API.

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async (`AsyncSession`, `select`, `insert … on conflict`), Pydantic v2

**File locations:**
- `src/audit/trace/repository.py` — `TraceIndexRepository`, `TraceSearchQuery`, `TraceSearchResult`
- `tests/audit/test_trace_index_repository.py`

---

### `TraceSearchQuery` and `TraceSearchResult`

```python
# src/audit/trace/repository.py
from __future__ import annotations
import uuid
from datetime  import datetime
from typing    import Sequence

from pydantic          import BaseModel, ConfigDict, Field
from sqlalchemy        import select, insert, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio         import AsyncSession

from src.audit.trace.models   import TraceRecord
from src.audit.trace.schemas  import TraceIndexEntry


class TraceSearchQuery(BaseModel):
    """Search filter for US-035 Replay Explorer (AC-4 columns)."""
    model_config = ConfigDict(frozen=True)

    user_id:            str | None = None
    intent:             str | None = None
    model_selected:     str | None = None
    governance_blocked: bool | None = None
    from_timestamp:     datetime | None = None
    to_timestamp:       datetime | None = None
    limit:              int = Field(default=50,  ge=1,  le=500)
    offset:             int = Field(default=0,   ge=0)


class TraceSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    items:      list[TraceIndexEntry]
    total:      int     # total rows matching the filter (for pagination)
    limit:      int
    offset:     int
```

---

### `TraceIndexRepository`

```python
class TraceIndexRepository:
    """
    Async repository for the execution_traces PostgreSQL search index (AC-4).

    Write strategy:
      INSERT … ON CONFLICT (request_id) DO UPDATE …
      This ensures idempotency — if the background write task is retried due to a
      transient DB error, the second attempt does not produce a duplicate row.
      It also handles the edge case where the MinIO write succeeds but the DB write
      was retried with an updated object_version.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Writes                                                               #
    # ------------------------------------------------------------------ #

    async def upsert(self, entry: TraceIndexEntry) -> None:
        """
        Insert or update a trace index row (AC-4).
        The full trace JSON lives in MinIO; this stores only searchable metadata
        plus the MinIO pointer (object_key, object_version).
        """
        stmt = (
            pg_insert(TraceRecord)
            .values(
                request_id         = entry.request_id,
                tenant_id          = entry.tenant_id,
                user_id            = entry.user_id,
                timestamp          = entry.timestamp,
                intent             = entry.intent,
                model_selected     = entry.model_selected,
                governance_blocked = entry.governance_blocked,
                opa_denied_count   = entry.opa_denied_count,
                object_key         = entry.object_key,
                object_version     = entry.object_version,
            )
            .on_conflict_do_update(
                index_elements = ["request_id"],
                set_            = {
                    "object_key":         entry.object_key,
                    "object_version":     entry.object_version,
                    "governance_blocked": entry.governance_blocked,
                    "opa_denied_count":   entry.opa_denied_count,
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
        result = await self._session.execute(
            select(TraceRecord).where(TraceRecord.request_id == request_id)
        )
        row = result.scalar_one_or_none()
        return _to_entry(row) if row else None

    async def search(
        self,
        tenant_id: str,
        query:     TraceSearchQuery,
    ) -> TraceSearchResult:
        """
        Search traces by any combination of: user_id, intent, model_selected,
        governance_blocked, from/to timestamp (AC-4).
        Results are ordered by timestamp DESC.
        """
        stmt = (
            select(TraceRecord)
            .where(TraceRecord.tenant_id == tenant_id)
        )
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
        from sqlalchemy import func, select as sa_select
        count_stmt = sa_select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total        = total_result.scalar_one()

        # Paginated result
        rows_result  = await self._session.execute(
            stmt.order_by(TraceRecord.timestamp.desc())
                .limit(query.limit)
                .offset(query.offset)
        )
        rows = rows_result.scalars().all()
        return TraceSearchResult(
            items  = [_to_entry(r) for r in rows],
            total  = total,
            limit  = query.limit,
            offset = query.offset,
        )


# ------------------------------------------------------------------ #
# Mapping helper                                                       #
# ------------------------------------------------------------------ #

def _to_entry(row: TraceRecord) -> TraceIndexEntry:
    return TraceIndexEntry(
        request_id         = row.request_id,
        tenant_id          = row.tenant_id,
        user_id            = row.user_id,
        timestamp          = row.timestamp,
        intent             = row.intent,
        model_selected     = row.model_selected,
        governance_blocked = row.governance_blocked,
        opa_denied_count   = row.opa_denied_count,
        object_key         = row.object_key,
        object_version     = row.object_version,
    )
```

## Acceptance Criteria

- [ ] `TraceIndexRepository.upsert()` inserts a new row when `request_id` is absent
- [ ] `TraceIndexRepository.upsert()` updates `object_key`, `object_version`, `governance_blocked`, `opa_denied_count` when `request_id` already exists — no duplicate rows (idempotent)
- [ ] `search()` filters correctly by each of: `user_id`, `intent`, `from_timestamp`, `to_timestamp` independently and in combination (AC-4)
- [ ] `search()` returns results in `timestamp DESC` order
- [ ] `search()` respects `limit` and `offset` for pagination; `total` reflects the unfiltered count
- [ ] `get_by_request_id()` returns `None` for an unknown `request_id` — no exception raised

## Dependencies

- TASK-US034-01 (`TraceRecord` ORM, `TraceIndexEntry`, Alembic `0015`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
