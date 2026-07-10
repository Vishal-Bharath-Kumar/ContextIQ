# TASK-US033-01 — Policy Schemas, `PolicyRecord` ORM, and Alembic Migration `0014`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US033-01 |
| User Story | US-033 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the Pydantic data-transfer objects and SQLAlchemy ORM model for governance policy versioning, then add the Alembic migration `0014_create_policy_definitions` that creates the `policy_definitions` table. These schemas are the data contracts consumed by `PolicyRepository` (TASK-US033-02) and `PolicyService` (TASK-US033-03). They also encode the audit fields (author, `activated_at`) required by AC-5.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2 (`ConfigDict(frozen=True)`), SQLAlchemy 2.x async (`mapped_column`, `DeclarativeBase`), Alembic

**File locations:**
- `src/governance/policy/schemas.py` — Pydantic DTOs
- `src/governance/policy/models.py` — `PolicyRecord` ORM model
- `migrations/versions/0014_create_policy_definitions.py` — Alembic migration

---

### Pydantic schemas

```python
# src/governance/policy/schemas.py
from __future__ import annotations
from datetime   import datetime
from enum       import StrEnum
from uuid       import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyStatus(StrEnum):
    DRAFT      = "draft"       # created, not yet active in OPA
    ACTIVE     = "active"      # currently enforced by OPA
    SUPERSEDED = "superseded"  # previously active; replaced by newer version
    ROLLED_BACK = "rolled_back" # was active, rolled back to a prior version


class PolicyCreate(BaseModel):
    """Payload for POST /v1/policies (AC-1)."""
    model_config = ConfigDict(frozen=True)

    name:        str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    version:     str = Field(min_length=1, max_length=64,
                             description="Semantic version string, e.g. '1.2.0'.")
    rego_body:   str = Field(min_length=1,
                             description="Raw Rego source that will be pushed to OPA.")


class PolicyVersion(BaseModel):
    """Read-only view of a single stored policy version (AC-2)."""
    model_config = ConfigDict(frozen=True)

    id:           UUID
    policy_group: str            # logical name grouping all versions
    version:      str
    description:  str
    rego_body:    str
    status:       PolicyStatus
    author:       str            # sub claim from JWT (AC-5)
    activated_at: datetime | None = None  # populated on first activation (AC-5)
    created_at:   datetime


class PolicySummary(BaseModel):
    """Compact view for list responses — excludes rego_body to keep response small."""
    model_config = ConfigDict(frozen=True)

    id:           UUID
    policy_group: str
    version:      str
    description:  str
    status:       PolicyStatus
    author:       str
    activated_at: datetime | None = None
    created_at:   datetime


class ActivateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    activated_version: str
    bundle_push_ok:    bool       # True if OPA accepted the bundle PUT
    activated_at:      datetime


class RollbackResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    restored_version:  str
    previous_active:   str
    activated_at:      datetime
```

---

### ORM model

```python
# src/governance/policy/models.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm              import mapped_column, Mapped, DeclarativeBase


class Base(DeclarativeBase):
    pass


class PolicyRecord(Base):
    """
    Stores every policy version ever submitted to ContextIQ.
    One row per (policy_group, version) pair.
    At most one row per policy_group may have status='active' at any time —
    enforced at the service layer, not by a DB constraint.
    """
    __tablename__ = "policy_definitions"
    __table_args__ = (
        UniqueConstraint("policy_group", "version", name="uq_policy_group_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_group: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version:      Mapped[str] = mapped_column(String(64),  nullable=False)
    description:  Mapped[str] = mapped_column(Text,        nullable=False, default="")
    rego_body:    Mapped[str] = mapped_column(Text,        nullable=False)
    status:       Mapped[str] = mapped_column(String(32),  nullable=False, default="draft")

    # Audit fields (AC-5)
    author:       Mapped[str]            = mapped_column(String(256), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
    )
```

---

### Alembic migration `0014_create_policy_definitions`

```python
# migrations/versions/0014_create_policy_definitions.py
"""create policy_definitions table

Revision ID: 0014
Revises:     0013
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision    = "0014"
down_revision = "0013"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "policy_definitions",
        sa.Column("id",           postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_group", sa.String(128), nullable=False),
        sa.Column("version",      sa.String(64),  nullable=False),
        sa.Column("description",  sa.Text,         nullable=False, server_default=""),
        sa.Column("rego_body",    sa.Text,         nullable=False),
        sa.Column("status",       sa.String(32),   nullable=False, server_default="draft"),
        sa.Column("author",       sa.String(256),  nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        "ix_policy_definitions_policy_group",
        "policy_definitions",
        ["policy_group"],
    )
    op.create_unique_constraint(
        "uq_policy_group_version",
        "policy_definitions",
        ["policy_group", "version"],
    )


def downgrade() -> None:
    op.drop_table("policy_definitions")
```

## Acceptance Criteria

- [ ] `PolicyCreate.rego_body` accepts multi-line Rego strings without truncation
- [ ] `PolicyStatus` enum covers `draft`, `active`, `superseded`, `rolled_back`
- [ ] `PolicyRecord.author` and `PolicyRecord.activated_at` are nullable-correct (author required, `activated_at` nullable until activation)
- [ ] `uq_policy_group_version` unique constraint is present in both the ORM `__table_args__` and the Alembic migration
- [ ] Migration `0014` revises `0013` (`create_chunk_index`)
- [ ] `alembic upgrade head` succeeds; `alembic downgrade -1` drops the table cleanly

## Dependencies

- Alembic chain through `0013_create_chunk_index` (TASK-US027-01)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
