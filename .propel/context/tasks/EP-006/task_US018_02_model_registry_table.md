# TASK-US018-02 — `model_registry` PostgreSQL Table, ORM Model, and Alembic Migration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US018-02 |
| User Story | US-018 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define the `model_registry` PostgreSQL table, the SQLAlchemy 2.x async ORM model, and the Alembic migration that applies the schema. This is the PostgreSQL source-of-truth for all registered AI models (TR-016). The schema accommodates all six registration payload fields plus audit columns.

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async (`mapped_column`, `DeclarativeBase`), Alembic, PostgreSQL 15

**File locations:**
- `src/model_registry/models/model.py` — `ModelRecord` ORM class
- `alembic/versions/0010_create_model_registry.py` — migration
- `tests/model_registry/test_model_orm.py`

**`ModelRecord` ORM model:**

```python
# src/model_registry/models/model.py
from datetime import datetime
from uuid     import UUID, uuid4
from sqlalchemy import String, Float, Integer, Boolean, ARRAY, Enum as PgEnum, text
from sqlalchemy.orm       import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PgUUID, JSONB
from src.db.base          import Base          # shared DeclarativeBase
from src.model_registry.schemas.model_definition import LatencyTier

class ModelRecord(Base):
    __tablename__ = "model_registry"

    id:                 Mapped[UUID]     = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_id:           Mapped[str]      = mapped_column(String(128), unique=True, nullable=False, index=True)
    provider:           Mapped[str]      = mapped_column(String(64),  nullable=False)
    context_window:     Mapped[int]      = mapped_column(Integer,     nullable=False)
    cost_per_1k_tokens: Mapped[float]    = mapped_column(Float,       nullable=False)
    latency_tier:       Mapped[str]      = mapped_column(
        PgEnum("fast", "medium", "slow", name="latency_tier_enum"), nullable=False
    )
    capabilities:       Mapped[list]     = mapped_column(JSONB, nullable=False, default=list)
    is_active:          Mapped[bool]     = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at:         Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    updated_at:         Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()"), onupdate=datetime.utcnow
    )
```

**Alembic migration:**

```python
# alembic/versions/0010_create_model_registry.py
"""Create model_registry table

Revision ID: 0010
Depends on: 0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

def upgrade() -> None:
    op.execute("CREATE TYPE latency_tier_enum AS ENUM ('fast', 'medium', 'slow')")
    op.create_table(
        "model_registry",
        sa.Column("id",                 UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id",           sa.String(128),     nullable=False),
        sa.Column("provider",           sa.String(64),      nullable=False),
        sa.Column("context_window",     sa.Integer(),       nullable=False),
        sa.Column("cost_per_1k_tokens", sa.Float(),         nullable=False),
        sa.Column("latency_tier",       sa.Enum("fast", "medium", "slow", name="latency_tier_enum"), nullable=False),
        sa.Column("capabilities",       JSONB(),            nullable=False, server_default="'[]'::jsonb"),
        sa.Column("is_active",          sa.Boolean(),       nullable=False, server_default=sa.text("true")),
        sa.Column("created_at",         sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at",         sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_model_registry_model_id", "model_registry", ["model_id"])
    op.create_index("idx_model_registry_is_active_cost", "model_registry", ["is_active", "cost_per_1k_tokens"])

def downgrade() -> None:
    op.drop_table("model_registry")
    op.execute("DROP TYPE latency_tier_enum")
```

**Index rationale:**
- `uq_model_registry_model_id` — enforces duplicate-registration constraint at DB level (backs the 409 check)
- `idx_model_registry_is_active_cost` — covers `WHERE is_active = true ORDER BY cost_per_1k_tokens ASC` used by `GET /v1/models`

## Acceptance Criteria

- [ ] Alembic migration `0010` applies cleanly on a fresh PostgreSQL 15 instance
- [ ] `model_id` column has a `UNIQUE` constraint — duplicate insert raises `IntegrityError`
- [ ] `capabilities` stored as `JSONB` — list of capability strings round-trips correctly
- [ ] `latency_tier_enum` PostgreSQL type is created by the migration and dropped on downgrade
- [ ] `is_active` defaults to `true` server-side without requiring explicit Python value
- [ ] `idx_model_registry_is_active_cost` index exists after migration

## Dependencies

- TASK-US018-01 (`LatencyTier` enum — values must match `latency_tier_enum` PostgreSQL type)
- EP-DATA-001 (PostgreSQL store — connection and `DeclarativeBase` already established)
- TASK-US002-02 (Alembic versioning convention — migration number follows existing sequence)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Migration tested against a real PostgreSQL instance in the CI database service
- [ ] `downgrade()` is implemented and tested — migration is reversible
- [ ] `mypy --strict` passes on `model.py`; no `ruff` lint errors
