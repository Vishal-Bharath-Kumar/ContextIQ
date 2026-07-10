# TASK-US050-02 — Alembic Migration Scripts for All Core Application Tables

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US050-02 |
| User Story | US-050 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Write Alembic migration scripts that create all eight core application tables in the correct dependency order (AC-2). The migration chain continues from the current head `0019_create_admin_audit_log` (created in US-044). Each table is defined with appropriate column types, nullability constraints, foreign keys, and indexes. The corresponding SQLAlchemy ORM models are written alongside the migrations so `alembic --autogenerate` remains usable for future schema changes. Migration failures raise a descriptive error and Alembic's transactional DDL ensures partial changes are rolled back (AC-4).

## Implementation Details

**Technology:** Alembic 1.13+, SQLAlchemy 2.x async, PostgreSQL 15, Python 3.11+, Pydantic v2

**File locations:**
- `alembic/versions/0020_create_core_app_tables.py` — single batched migration for all 8 tables
- `src/data/models/connector_config.py`
- `src/data/models/knowledge_source.py`
- `src/data/models/knowledge_chunk.py`
- `src/data/models/model_registry.py`
- `src/data/models/policy.py`
- `src/data/models/audit_log.py`
- `src/data/models/execution_trace_index.py`
- `src/data/models/sync_job.py`
- `src/data/models/base.py` — shared `DeclarativeBase`

---

### Alembic migration

```python
# alembic/versions/0020_create_core_app_tables.py
"""Create core application tables.

Revision ID: 0020
Revises:     0019
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# Enums defined once; reused across tables
CONNECTOR_TYPE_ENUM = ENUM(
    "confluence", "jira", "github", "gitlab", "slack", "sharepoint",
    "notion", "web_crawler", "custom",
    name="connector_type_enum",
    create_type=True,
)
SYNC_STATUS_ENUM = ENUM(
    "pending", "running", "success", "failed", "cancelled",
    name="sync_status_enum",
    create_type=True,
)
POLICY_TYPE_ENUM = ENUM(
    "routing", "access_control", "cost_limit", "rate_limit",
    name="policy_type_enum",
    create_type=True,
)
MODEL_STATUS_ENUM = ENUM(
    "active", "deprecated", "retired",
    name="model_status_enum",
    create_type=True,
)


def upgrade() -> None:
    # AC-4: all DDL runs in a single transaction — any failure rolls back all changes
    CONNECTOR_TYPE_ENUM.create(op.get_bind(), checkfirst=True)
    SYNC_STATUS_ENUM.create(op.get_bind(), checkfirst=True)
    POLICY_TYPE_ENUM.create(op.get_bind(), checkfirst=True)
    MODEL_STATUS_ENUM.create(op.get_bind(), checkfirst=True)

    # -----------------------------------------------------------------------
    # Table 1: connector_config
    # -----------------------------------------------------------------------
    op.create_table(
        "connector_config",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name",         sa.String(255),  nullable=False),
        sa.Column("connector_type", CONNECTOR_TYPE_ENUM, nullable=False),
        sa.Column("vault_path",   sa.String(512),  nullable=False,
                  comment="Vault KV path where credentials are stored (TASK-US047-02)"),
        sa.Column("config",       JSONB,           nullable=False, server_default="{}"),
        sa.Column("enabled",      sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("created_by",   sa.String(255),  nullable=False),
        sa.Column("created_at",   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()"),
                  onupdate=sa.text("now()")),
    )
    op.create_index("ix_connector_config_type",    "connector_config", ["connector_type"])
    op.create_index("ix_connector_config_enabled", "connector_config", ["enabled"])

    # -----------------------------------------------------------------------
    # Table 2: knowledge_source
    # -----------------------------------------------------------------------
    op.create_table(
        "knowledge_source",
        sa.Column("id",              UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("connector_id",    UUID(as_uuid=True), nullable=False),
        sa.Column("source_uri",      sa.Text(),    nullable=False),
        sa.Column("title",           sa.String(512), nullable=True),
        sa.Column("content_hash",    sa.String(64),  nullable=True,
                  comment="SHA-256 of raw content; used for dedup detection"),
        sa.Column("last_indexed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata",        JSONB,         nullable=False, server_default="{}"),
        sa.Column("created_at",      sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["connector_id"], ["connector_config.id"],
            name="fk_knowledge_source_connector", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_knowledge_source_connector_id", "knowledge_source", ["connector_id"])
    op.create_index("ix_knowledge_source_content_hash", "knowledge_source", ["content_hash"])
    op.create_index("ix_knowledge_source_last_indexed", "knowledge_source", ["last_indexed_at"])

    # -----------------------------------------------------------------------
    # Table 3: knowledge_chunk
    # -----------------------------------------------------------------------
    op.create_table(
        "knowledge_chunk",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id",   UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(),  nullable=False,
                  comment="Zero-based position of this chunk within the source document"),
        sa.Column("content",     sa.Text(),     nullable=False),
        sa.Column("token_count", sa.Integer(),  nullable=True),
        sa.Column("embedding_id", sa.String(128), nullable=True,
                  comment="Reference ID in Qdrant vector store"),
        sa.Column("metadata",    JSONB,         nullable=False, server_default="{}"),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_source.id"],
            name="fk_knowledge_chunk_source", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_knowledge_chunk_source_idx"),
    )
    op.create_index("ix_knowledge_chunk_source_id",   "knowledge_chunk", ["source_id"])
    op.create_index("ix_knowledge_chunk_embedding_id", "knowledge_chunk", ["embedding_id"])

    # -----------------------------------------------------------------------
    # Table 4: model_registry
    # -----------------------------------------------------------------------
    op.create_table(
        "model_registry",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id",     sa.String(255), nullable=False, unique=True,
                  comment="Canonical model identifier e.g. gpt-4o, claude-3-5-sonnet"),
        sa.Column("provider",     sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("cost_per_input_token",  sa.Numeric(18, 8), nullable=True),
        sa.Column("cost_per_output_token", sa.Numeric(18, 8), nullable=True),
        sa.Column("status",        MODEL_STATUS_ENUM, nullable=False, server_default="active"),
        sa.Column("capabilities",  JSONB, nullable=False, server_default="{}",
                  comment="Feature flags e.g. {\"tool_use\": true, \"vision\": false}"),
        sa.Column("config",        JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",    sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_model_registry_provider", "model_registry", ["provider"])
    op.create_index("ix_model_registry_status",   "model_registry", ["status"])

    # -----------------------------------------------------------------------
    # Table 5: policy
    # -----------------------------------------------------------------------
    op.create_table(
        "policy",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name",        sa.String(255),  nullable=False, unique=True),
        sa.Column("policy_type", POLICY_TYPE_ENUM, nullable=False),
        sa.Column("rules",       JSONB,           nullable=False,
                  comment="Rego-compatible rule definition or routing weight map"),
        sa.Column("enabled",     sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("priority",    sa.Integer(),    nullable=False, server_default="100",
                  comment="Evaluation order; lower number = higher priority"),
        sa.Column("created_by",  sa.String(255),  nullable=False),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_policy_type",    "policy", ["policy_type"])
    op.create_index("ix_policy_enabled", "policy", ["enabled"])
    op.create_index("ix_policy_priority","policy", ["priority"])

    # -----------------------------------------------------------------------
    # Table 6: audit_log (application-level event log; distinct from admin_audit_log)
    # -----------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type",  sa.String(128),   nullable=False),
        sa.Column("user_id",     sa.String(255),   nullable=True),
        sa.Column("resource_type", sa.String(128), nullable=False),
        sa.Column("resource_id",   sa.String(255), nullable=True),
        sa.Column("details",     JSONB,            nullable=False, server_default="{}"),
        sa.Column("ip_address",  sa.String(45),    nullable=True),
        sa.Column("user_agent",  sa.Text(),        nullable=True),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_log_event_type",    "audit_log", ["event_type"])
    op.create_index("ix_audit_log_user_id",       "audit_log", ["user_id"])
    op.create_index("ix_audit_log_resource",      "audit_log", ["resource_type", "resource_id"])
    op.create_index("ix_audit_log_created_at",    "audit_log", ["created_at"])
    # Partial index: fast query for recent events (AC-6 read replica reporting)
    op.execute(
        "CREATE INDEX ix_audit_log_recent ON audit_log (created_at DESC) "
        "WHERE created_at > now() - interval '90 days'"
    )

    # -----------------------------------------------------------------------
    # Table 7: execution_trace_index
    # -----------------------------------------------------------------------
    op.create_table(
        "execution_trace_index",
        sa.Column("id",            UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trace_id",      sa.String(128),  nullable=False, unique=True,
                  comment="OTLP trace ID — links to full trace in MinIO contextiq-traces bucket"),
        sa.Column("request_id",    sa.String(128),  nullable=True),
        sa.Column("user_id",       sa.String(255),  nullable=True),
        sa.Column("model_id",      sa.String(255),  nullable=True),
        sa.Column("input_tokens",  sa.Integer(),    nullable=True),
        sa.Column("output_tokens", sa.Integer(),    nullable=True),
        sa.Column("latency_ms",    sa.Integer(),    nullable=True),
        sa.Column("error",         sa.Text(),       nullable=True),
        sa.Column("metadata",      JSONB,           nullable=False, server_default="{}"),
        sa.Column("started_at",    sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at",   sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_exec_trace_trace_id",    "execution_trace_index", ["trace_id"])
    op.create_index("ix_exec_trace_user_id",     "execution_trace_index", ["user_id"])
    op.create_index("ix_exec_trace_model_id",    "execution_trace_index", ["model_id"])
    op.create_index("ix_exec_trace_started_at",  "execution_trace_index", ["started_at"])

    # -----------------------------------------------------------------------
    # Table 8: sync_job
    # -----------------------------------------------------------------------
    op.create_table(
        "sync_job",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("connector_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status",       SYNC_STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("started_at",   sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at",  sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("items_synced", sa.Integer(),  nullable=True, server_default="0"),
        sa.Column("items_failed", sa.Integer(),  nullable=True, server_default="0"),
        sa.Column("error_log",    sa.Text(),     nullable=True),
        sa.Column("triggered_by", sa.String(64), nullable=False,
                  comment="'manual', 'schedule', or 'webhook'"),
        sa.Column("created_at",   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["connector_id"], ["connector_config.id"],
            name="fk_sync_job_connector", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_sync_job_connector_id", "sync_job", ["connector_id"])
    op.create_index("ix_sync_job_status",       "sync_job", ["status"])
    op.create_index("ix_sync_job_started_at",   "sync_job", ["started_at"])


def downgrade() -> None:
    op.drop_table("sync_job")
    op.drop_table("execution_trace_index")
    op.drop_table("audit_log")
    op.drop_table("policy")
    op.drop_table("model_registry")
    op.drop_table("knowledge_chunk")
    op.drop_table("knowledge_source")
    op.drop_table("connector_config")
    CONNECTOR_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
    SYNC_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    POLICY_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
    MODEL_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
```

---

### SQLAlchemy ORM models

```python
# src/data/models/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
# src/data/models/connector_config.py
from __future__ import annotations
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.base import Base


class ConnectorType(str, enum.Enum):
    CONFLUENCE = "confluence"
    JIRA       = "jira"
    GITHUB     = "github"
    GITLAB     = "gitlab"
    SLACK      = "slack"
    SHAREPOINT = "sharepoint"
    NOTION     = "notion"
    WEB_CRAWLER= "web_crawler"
    CUSTOM     = "custom"


class ConnectorConfig(Base):
    __tablename__ = "connector_config"

    id:             Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name:           Mapped[str]         = mapped_column(String(255), nullable=False)
    connector_type: Mapped[ConnectorType] = mapped_column(Enum(ConnectorType, name="connector_type_enum"), nullable=False)
    vault_path:     Mapped[str]         = mapped_column(String(512), nullable=False)
    config:         Mapped[dict]        = mapped_column(JSONB, nullable=False, default={})
    enabled:        Mapped[bool]        = mapped_column(Boolean, nullable=False, default=True)
    created_by:     Mapped[str]         = mapped_column(String(255), nullable=False)
    created_at:     Mapped[datetime]    = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at:     Mapped[datetime]    = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    knowledge_sources: Mapped[list["KnowledgeSource"]] = relationship("KnowledgeSource", back_populates="connector", cascade="all, delete-orphan")
    sync_jobs:         Mapped[list["SyncJob"]]         = relationship("SyncJob",         back_populates="connector", cascade="all, delete-orphan")
```

```python
# src/data/models/sync_job.py
from __future__ import annotations
import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.base import Base


class SyncStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class SyncJob(Base):
    __tablename__ = "sync_job"

    id:           Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    connector_id: Mapped[uuid.UUID]  = mapped_column(ForeignKey("connector_config.id", ondelete="CASCADE"), nullable=False)
    status:       Mapped[SyncStatus] = mapped_column(Enum(SyncStatus, name="sync_status_enum"), nullable=False, default=SyncStatus.PENDING)
    started_at:   Mapped[datetime | None]  = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at:  Mapped[datetime | None]  = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    items_synced: Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    items_failed: Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    error_log:    Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str]        = mapped_column(String(64), nullable=False)
    created_at:   Mapped[datetime]   = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    connector: Mapped["ConnectorConfig"] = relationship("ConnectorConfig", back_populates="sync_jobs")
```

*(Remaining 6 ORM models — `knowledge_source.py`, `knowledge_chunk.py`, `model_registry.py`, `policy.py`, `audit_log.py`, `execution_trace_index.py` — follow the same pattern as above: one file per model, typed `mapped_column` attributes, relationships where applicable.)*

## Acceptance Criteria

- [ ] `alembic upgrade head` from `0019` completes without error; `alembic current` shows `0020 (head)` (AC-2)
- [ ] `psql -c "\dt"` shows all 8 tables: `connector_config`, `knowledge_source`, `knowledge_chunk`, `model_registry`, `policy`, `audit_log`, `execution_trace_index`, `sync_job` (AC-2)
- [ ] `alembic downgrade 0019` drops all 8 tables and all 4 ENUM types cleanly (AC-4)
- [ ] `alembic upgrade 0020` after `downgrade 0019` re-creates all tables (idempotent up/down cycle) (AC-4)
- [ ] `alembic check` (autogenerate comparison) shows no pending schema differences after migration is applied (AC-2)
- [ ] All FK constraints verified: `psql -c "\d+ knowledge_chunk"` shows FK to `knowledge_source.id` (AC-2)

## Dependencies

- TASK-US050-01 — PostgreSQL must be running and reachable for migration execution
- `alembic.ini` `sqlalchemy.url` must be configured via environment variable (not hard-coded)
- Existing migration chain must end at `0019` — check with `alembic current` before applying

## Definition of Done

- [ ] `alembic/versions/0020_create_core_app_tables.py` committed with passing `alembic upgrade head` in CI
- [ ] All 8 ORM model files created in `src/data/models/`
- [ ] Unit tests in `tests/unit/test_models.py` assert that each model can be instantiated with required fields
