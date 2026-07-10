# TASK-US026-01 — `SyncJobRecord` ORM, `SyncJobRepository`, and Alembic Migration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US026-01 |
| User Story | US-026 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the `sync_jobs` PostgreSQL table, the SQLAlchemy 2.x async ORM model, the `SyncJobStatus` enum, and `SyncJobRepository`. This is the persistence layer for sync job lifecycle tracking (US-026 AC-3: status running/succeeded/failed recorded in PostgreSQL) and the data source for the on-demand status endpoint (TASK-US026-04).

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async, Alembic, PostgreSQL 15

**File locations:**
- `src/knowledge_sources/models/sync_job.py` — `SyncJobRecord`, `SyncJobStatus`
- `src/knowledge_sources/repositories/sync_job_repository.py` — `SyncJobRepository`
- `alembic/versions/0012_create_sync_jobs.py` — migration
- `tests/knowledge_sources/test_sync_job_repository.py`

**`SyncJobStatus`:**

```python
# src/knowledge_sources/models/sync_job.py
from enum import StrEnum

class SyncJobStatus(StrEnum):
    RUNNING   = "running"    # job in progress
    SUCCEEDED = "succeeded"  # completed without error
    FAILED    = "failed"     # all retry attempts exhausted
```

**`SyncJobRecord` ORM:**

```python
# src/knowledge_sources/models/sync_job.py
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Enum as PgEnum, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from src.db.base import Base

class SyncJobRecord(Base):
    __tablename__ = "sync_jobs"

    id:               Mapped[UUID]     = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id:        Mapped[UUID]     = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status:           Mapped[str]      = mapped_column(
        PgEnum("running", "succeeded", "failed", name="sync_job_status_enum"),
        nullable=False,
        server_default="running",
    )
    attempt_number:   Mapped[int]      = mapped_column(Integer,  nullable=False, server_default=text("1"))
    is_full_sync:     Mapped[bool]     = mapped_column(Boolean,  nullable=False, server_default=text("false"))
    started_at:       Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    completed_at:     Mapped[datetime | None] = mapped_column(nullable=True)
    duration_s:       Mapped[float | None]    = mapped_column(Float, nullable=True)
    items_processed:  Mapped[int | None]      = mapped_column(Integer, nullable=True)
    items_failed:     Mapped[int | None]      = mapped_column(Integer, nullable=True)
    error_message:    Mapped[str | None]      = mapped_column(String(2000), nullable=True)
```

**`SyncJobRepository`:**

```python
# src/knowledge_sources/repositories/sync_job_repository.py
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.knowledge_sources.models.sync_job import SyncJobRecord, SyncJobStatus

class SyncJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, source_id: UUID, attempt_number: int = 1, is_full_sync: bool = False) -> SyncJobRecord:
        record = SyncJobRecord(
            source_id      = source_id,
            status         = SyncJobStatus.RUNNING,
            attempt_number = attempt_number,
            is_full_sync   = is_full_sync,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def mark_succeeded(
        self, job_id: UUID, items_processed: int, items_failed: int, duration_s: float
    ) -> None:
        record = await self._get(job_id)
        if record:
            record.status          = SyncJobStatus.SUCCEEDED
            record.completed_at    = datetime.now(tz=timezone.utc)
            record.duration_s      = duration_s
            record.items_processed = items_processed
            record.items_failed    = items_failed
            await self._session.flush()

    async def mark_failed(self, job_id: UUID, error_message: str, duration_s: float) -> None:
        record = await self._get(job_id)
        if record:
            record.status       = SyncJobStatus.FAILED
            record.completed_at = datetime.now(tz=timezone.utc)
            record.duration_s   = duration_s
            record.error_message = error_message[:2000]
            await self._session.flush()

    async def get(self, job_id: UUID) -> SyncJobRecord | None:
        return await self._get(job_id)

    async def list_by_source(self, source_id: UUID, limit: int = 10) -> list[SyncJobRecord]:
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
```

**Alembic migration `0012_create_sync_jobs.py`:**

```python
def upgrade() -> None:
    op.execute("CREATE TYPE sync_job_status_enum AS ENUM ('running','succeeded','failed')")
    op.create_table(
        "sync_jobs",
        sa.Column("id",              postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id",       postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status",          sa.Enum(name="sync_job_status_enum"), nullable=False, server_default="running"),
        sa.Column("attempt_number",  sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_full_sync",    sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("started_at",      sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_s",      sa.Float(), nullable=True),
        sa.Column("items_processed", sa.Integer(), nullable=True),
        sa.Column("items_failed",    sa.Integer(), nullable=True),
        sa.Column("error_message",   sa.String(2000), nullable=True),
    )
    op.create_index("idx_sync_jobs_source_id_started", "sync_jobs", ["source_id", "started_at"])

def downgrade() -> None:
    op.drop_table("sync_jobs")
    op.execute("DROP TYPE IF EXISTS sync_job_status_enum")
```

## Acceptance Criteria

- [ ] `SyncJobRecord` inserts with `status="running"` and `completed_at=NULL` on creation
- [ ] `mark_succeeded()` sets `status="succeeded"`, `completed_at`, `duration_s`, `items_processed`
- [ ] `mark_failed()` truncates `error_message` to 2 000 chars
- [ ] `list_by_source()` returns records ordered by `started_at DESC`
- [ ] `CASCADE` delete: dropping a `KnowledgeSourceRecord` deletes its `SyncJobRecord` rows
- [ ] Alembic `upgrade` / `downgrade` round-trips cleanly

## Dependencies

- TASK-US025-01 (`knowledge_sources` table — FK target for `source_id`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Alembic version chain: follows `0011_create_knowledge_sources`
- [ ] `mypy --strict` passes; no `ruff` lint errors
