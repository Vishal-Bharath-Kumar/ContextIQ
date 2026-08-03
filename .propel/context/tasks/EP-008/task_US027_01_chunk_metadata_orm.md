# TASK-US027-01 — `ChunkRecord` ORM, Pydantic Schemas, and Alembic Migration `0013`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US027-01 |
| User Story | US-027 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define the `chunk_index` PostgreSQL table, the SQLAlchemy 2.x async ORM model (`ChunkRecord`), the Alembic migration `0013_create_chunk_index`, and the Pydantic schemas used across the indexing pipeline. This is the data foundation for AC-5 (PostgreSQL chunk metadata) and the lookup table used by the stale-embedding deletion path (AC-7).

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async, Alembic, Pydantic v2, PostgreSQL 15

**File locations:**
- `src/indexing/models/chunk.py` — `ChunkRecord` ORM
- `src/indexing/schemas/chunk.py` — `ChunkMetadata`, `ChunkPayload`, `IndexedChunk`
- `alembic/versions/0013_create_chunk_index.py` — migration
- `tests/indexing/test_chunk_orm.py`

**Pydantic schemas:**

```python
# src/indexing/schemas/chunk.py
from __future__ import annotations
from datetime    import datetime
from uuid        import UUID, uuid4
from pydantic    import BaseModel, ConfigDict, Field

class ChunkPayload(BaseModel):
    """Raw text chunk produced by a connector, ready for embedding."""
    model_config = ConfigDict(frozen=True)

    chunk_id:    UUID   = Field(default_factory=uuid4)
    source_id:   UUID
    tenant_id:   str    = Field(min_length=1, max_length=128)
    document_id: str    = Field(
        description="Connector-native document identifier, e.g. 'github:owner/repo:sha'",
        min_length=1, max_length=512,
    )
    text:        str    = Field(min_length=1)
    token_count: int    = Field(ge=1)
    metadata:    dict   = Field(default_factory=dict)


class ChunkMetadata(BaseModel):
    """Row written to PostgreSQL after successful indexing."""
    model_config = ConfigDict(frozen=True)

    chunk_id:        UUID
    source_id:       UUID
    tenant_id:       str
    document_id:     str
    embedding_model: str
    token_count:     int
    indexed_at:      datetime


class IndexedChunk(BaseModel):
    """Combines raw payload with its generated embedding vector."""
    model_config = ConfigDict(frozen=True)

    payload:   ChunkPayload
    vector:    list[float]
    model_id:  str
```

**`ChunkRecord` ORM:**

```python
# src/indexing/models/chunk.py
from __future__ import annotations
from datetime   import datetime
from uuid       import UUID
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm           import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from src.database.base        import Base

class ChunkRecord(Base):
    __tablename__ = "chunk_index"

    chunk_id:        Mapped[UUID]     = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id:       Mapped[UUID]     = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="FK to knowledge_sources.id (not enforced as FK for write throughput)",
    )
    tenant_id:       Mapped[str]      = mapped_column(String(128), nullable=False)
    document_id:     Mapped[str]      = mapped_column(String(512), nullable=False, index=True)
    embedding_model: Mapped[str]      = mapped_column(String(128), nullable=False)
    token_count:     Mapped[int]      = mapped_column(Integer, nullable=False)
    indexed_at:      Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
```

**Notes on `source_id` FK:**
The FK to `knowledge_sources.id` is intentionally omitted as a database-level constraint. At 1,000 chunks/min throughput, FK validation on every insert would add lock contention on the parent table. The application layer guarantees referential integrity before dispatching the indexing pipeline.

**Alembic migration `0013_create_chunk_index`:**

```python
# alembic/versions/0013_create_chunk_index.py
"""create chunk_index table

Revision ID: 0013
Revises:     0012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

def upgrade() -> None:
    op.create_table(
        "chunk_index",
        sa.Column("chunk_id",        UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id",       UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id",       sa.String(128),     nullable=False),
        sa.Column("document_id",     sa.String(512),     nullable=False),
        sa.Column("embedding_model", sa.String(128),     nullable=False),
        sa.Column("token_count",     sa.Integer(),       nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_chunk_index_source_id",   "chunk_index", ["source_id"])
    op.create_index("ix_chunk_index_document_id", "chunk_index", ["document_id"])

def downgrade() -> None:
    op.drop_table("chunk_index")
```

**`ChunkRepository`:**

```python
# src/indexing/repositories/chunk_repository.py
from uuid            import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy             import select, delete
from src.indexing.models.chunk  import ChunkRecord
from src.indexing.schemas.chunk import ChunkMetadata

class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_batch(self, chunks: list[ChunkMetadata]) -> None:
        """INSERT … ON CONFLICT (chunk_id) DO UPDATE — idempotent re-indexing."""
        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(ChunkRecord).values(
            [c.model_dump() for c in chunks]
        ).on_conflict_do_update(
            index_elements=["chunk_id"],
            set_={
                "embedding_model": insert(ChunkRecord).excluded.embedding_model,
                "token_count":     insert(ChunkRecord).excluded.token_count,
                "indexed_at":      insert(ChunkRecord).excluded.indexed_at,
            },
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
        return result.rowcount
```

## Acceptance Criteria

- [ ] `chunk_index` table created by running `alembic upgrade head` against a clean PostgreSQL 15 DB
- [ ] `ChunkRepository.upsert_batch()` is idempotent: inserting the same `chunk_id` twice updates `indexed_at` without error
- [ ] `ix_chunk_index_source_id` and `ix_chunk_index_document_id` indexes present in `\d chunk_index`
- [ ] `ChunkPayload`, `ChunkMetadata`, `IndexedChunk` are all frozen (`ConfigDict(frozen=True)`)
- [ ] `mypy --strict` passes on `src/indexing/models/chunk.py` and `src/indexing/schemas/chunk.py`

## Dependencies

- TASK-US025-01 (`KnowledgeSourceRecord`, migration chain through `0012`)
- TASK-US026-01 (migration `0012_create_sync_jobs` — this migration revises `0012`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Migration tested with `alembic upgrade 0013` and `alembic downgrade 0012`
- [ ] `mypy --strict` passes; no `ruff` lint errors
