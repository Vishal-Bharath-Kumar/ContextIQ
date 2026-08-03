# TASK-US034-01 — `ExecutionTrace` Schemas, `TraceRecord` ORM, and Alembic Migration `0015`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US034-01 |
| User Story | US-034 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the Pydantic data-transfer objects that represent the complete execution trace structure and the SQLAlchemy `TraceRecord` ORM model used for the PostgreSQL search index. Add Alembic migration `0015_create_execution_traces` to create the `execution_traces` table. These schemas are the single source of truth shared by the MinIO writer (TASK-US034-02), the index repository (TASK-US034-03), and the trace writer node (TASK-US034-04). US-035 (Replay Explorer) reads from these structures.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2 (`ConfigDict(frozen=True)`), SQLAlchemy 2.x async (`mapped_column`, `DeclarativeBase`), Alembic

**File locations:**
- `src/audit/trace/schemas.py` — Pydantic DTOs
- `src/audit/trace/models.py` — `TraceRecord` ORM model
- `migrations/versions/0015_create_execution_traces.py` — Alembic migration

---

### Pydantic schemas

```python
# src/audit/trace/schemas.py
from __future__ import annotations
from datetime   import datetime
from uuid       import UUID

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------ #
# Sub-structures (AC-2 field breakdown)                               #
# ------------------------------------------------------------------ #

class RetrievedChunkSummary(BaseModel):
    """Lightweight summary of a single retrieved context chunk."""
    model_config = ConfigDict(frozen=True)

    chunk_id:             str
    source_id:            str
    relevance_score:      float
    classification_label: str = "internal"
    redacted:             bool = False    # True if governance_node applied redaction
    opa_denied:           bool = False    # True if opa_filter_node denied this chunk


class CompressionDelta(BaseModel):
    """Token counts before and after compression (for US-035 detail view)."""
    model_config = ConfigDict(frozen=True)

    tokens_before:  int
    tokens_after:   int
    chunks_before:  int
    chunks_after:   int

    @property
    def reduction_pct(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return round(100 * (1 - self.tokens_after / self.tokens_before), 1)


class GovernanceDecisionSummary(BaseModel):
    """Condensed governance and OPA filter outcomes for the trace."""
    model_config = ConfigDict(frozen=True)

    findings_count:    int  = 0
    redacted_count:    int  = 0
    opa_denied_count:  int  = 0
    opa_bundle_version: str = "unknown"
    governance_blocked: bool = False


class ExecutionPlanStep(BaseModel):
    """One entry in the execution_trace list from AgentState (AC-2)."""
    model_config = ConfigDict(frozen=True)

    node:     str
    eval_ms:  float | None = None
    metadata: dict         = Field(default_factory=dict)


# ------------------------------------------------------------------ #
# Root trace document written to MinIO and indexed in PostgreSQL      #
# ------------------------------------------------------------------ #

class ExecutionTrace(BaseModel):
    """
    Immutable execution trace — one document per request.

    All fields map to AC-2 required properties:
      request_id, user_id, timestamp, prompt, intent,
      execution_plan, retrieved_chunks (pre + post compression),
      governance_decisions, model_selected, response_summary.
    """
    model_config = ConfigDict(frozen=True)

    # Identity
    request_id:  UUID
    tenant_id:   str
    user_id:     str   # sub claim from JWT

    # Timing (AC-2: timestamp)
    timestamp:   datetime
    latency_ms:  float | None = None

    # Content (AC-2: prompt, intent)
    prompt:      str
    intent:      str   # classification result, e.g. "technical_support"

    # Pipeline steps (AC-2: execution_plan)
    execution_plan: list[ExecutionPlanStep] = Field(default_factory=list)

    # Retrieval (AC-2: retrieved_chunks pre- and post-compression)
    retrieved_chunks_pre_compression:  list[RetrievedChunkSummary] = Field(
        default_factory=list
    )
    retrieved_chunks_post_compression: list[RetrievedChunkSummary] = Field(
        default_factory=list
    )
    compression_delta: CompressionDelta | None = None

    # Governance (AC-2: governance_decisions)
    governance_decisions: GovernanceDecisionSummary = Field(
        default_factory=GovernanceDecisionSummary
    )

    # Model routing (AC-2: model_selected)
    model_selected:  str | None = None
    prompt_tokens:   int | None = None
    completion_tokens: int | None = None

    # Output (AC-2: response_summary)
    response_summary: str | None = None   # first 500 chars of the model response

    # Object store location (populated after MinIO write)
    object_key:      str | None = None
    object_version:  str | None = None


class TraceIndexEntry(BaseModel):
    """
    Columns written to PostgreSQL for search (AC-4).
    Subset of ExecutionTrace; excludes large text fields.
    """
    model_config = ConfigDict(frozen=True)

    request_id:        UUID
    tenant_id:         str
    user_id:           str
    timestamp:         datetime
    intent:            str
    model_selected:    str | None = None
    governance_blocked: bool = False
    opa_denied_count:  int  = 0
    object_key:        str  = ""
    object_version:    str  = ""
```

---

### ORM model

```python
# src/audit/trace/models.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy                      import String, Boolean, Integer, DateTime, Index
from sqlalchemy.dialects.postgresql  import UUID as PGUUID
from sqlalchemy.orm                  import mapped_column, Mapped, DeclarativeBase


class Base(DeclarativeBase):
    pass


class TraceRecord(Base):
    """
    PostgreSQL search index for execution traces (AC-4).
    Full trace JSON lives in MinIO; this table holds only searchable metadata.

    Indexed on: request_id (unique), user_id, timestamp, intent (AC-4).
    """
    __tablename__ = "execution_traces"

    # Search columns (AC-4)
    request_id:  Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True
    )
    tenant_id:   Mapped[str]  = mapped_column(String(128), nullable=False)
    user_id:     Mapped[str]  = mapped_column(String(256), nullable=False)
    timestamp:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    intent:      Mapped[str]  = mapped_column(String(128), nullable=False, index=True)

    # Governance summary columns — support US-035 search filters
    model_selected:     Mapped[str | None]  = mapped_column(String(128), nullable=True)
    governance_blocked: Mapped[bool]        = mapped_column(Boolean, default=False)
    opa_denied_count:   Mapped[int]         = mapped_column(Integer,  default=0)

    # MinIO pointer
    object_key:     Mapped[str] = mapped_column(String(512), nullable=False)
    object_version: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    # Composite indexes for common US-035 search patterns
    __table_args__ = (
        Index("ix_traces_user_timestamp", "user_id", "timestamp"),
        Index("ix_traces_tenant_timestamp", "tenant_id", "timestamp"),
    )
```

---

### Alembic migration `0015_create_execution_traces`

```python
# migrations/versions/0015_create_execution_traces.py
"""create execution_traces table

Revision ID: 0015
Revises:     0014
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = "0015"
down_revision = "0014"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "execution_traces",
        sa.Column("request_id",         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id",          sa.String(128),  nullable=False),
        sa.Column("user_id",            sa.String(256),  nullable=False),
        sa.Column("timestamp",          sa.DateTime(timezone=True), nullable=False),
        sa.Column("intent",             sa.String(128),  nullable=False),
        sa.Column("model_selected",     sa.String(128),  nullable=True),
        sa.Column("governance_blocked", sa.Boolean,      nullable=False, server_default="false"),
        sa.Column("opa_denied_count",   sa.Integer,      nullable=False, server_default="0"),
        sa.Column("object_key",         sa.String(512),  nullable=False),
        sa.Column("object_version",     sa.String(256),  nullable=False, server_default=""),
    )
    op.create_index("ix_traces_timestamp",        "execution_traces", ["timestamp"])
    op.create_index("ix_traces_intent",           "execution_traces", ["intent"])
    op.create_index("ix_traces_user_timestamp",   "execution_traces", ["user_id", "timestamp"])
    op.create_index("ix_traces_tenant_timestamp", "execution_traces", ["tenant_id", "timestamp"])


def downgrade() -> None:
    op.drop_table("execution_traces")
```

## Acceptance Criteria

- [ ] `ExecutionTrace` contains all fields listed in AC-2: `request_id`, `user_id`, `timestamp`, `prompt`, `intent`, `execution_plan`, `retrieved_chunks` (pre + post), `governance_decisions`, `model_selected`, `response_summary`
- [ ] `ExecutionTrace` is frozen (immutable Pydantic model) — mutation raises `ValidationError`
- [ ] `TraceRecord` table has indexes on `user_id`, `timestamp`, `intent`, and the composites `(user_id, timestamp)`, `(tenant_id, timestamp)` (AC-4)
- [ ] Migration `0015` revises `0014` (`create_policy_definitions`)
- [ ] `alembic upgrade head` succeeds; `alembic downgrade -1` drops the table cleanly

## Dependencies

- Alembic chain through `0014_create_policy_definitions` (TASK-US033-01)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
