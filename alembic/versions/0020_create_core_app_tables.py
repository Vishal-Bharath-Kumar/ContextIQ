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

# Enums defined once; reused across tables.
# create_type=False because upgrade() explicitly calls .create(bind,
# checkfirst=True) on each before they're used as column types below —
# leaving create_type=True would make create_table() attempt to create
# them a second time within the same migration and fail.
CONNECTOR_TYPE_ENUM = ENUM(
    "confluence", "jira", "github", "gitlab", "slack", "sharepoint",
    "notion", "web_crawler", "custom",
    name="connector_type_enum",
    create_type=False,
)
SYNC_STATUS_ENUM = ENUM(
    "pending", "running", "success", "failed", "cancelled",
    name="sync_status_enum",
    create_type=False,
)
POLICY_TYPE_ENUM = ENUM(
    "routing", "access_control", "cost_limit", "rate_limit",
    name="policy_type_enum",
    create_type=False,
)
MODEL_STATUS_ENUM = ENUM(
    "active", "deprecated", "retired",
    name="model_status_enum",
    create_type=False,
)


def upgrade() -> None:
    # AC-4: all DDL runs in a single transaction — any failure rolls back all changes
    bind = op.get_bind()
    CONNECTOR_TYPE_ENUM.create(bind, checkfirst=True)
    SYNC_STATUS_ENUM.create(bind, checkfirst=True)
    POLICY_TYPE_ENUM.create(bind, checkfirst=True)
    MODEL_STATUS_ENUM.create(bind, checkfirst=True)

    # -----------------------------------------------------------------------
    # Table 1: connector_config
    # -----------------------------------------------------------------------
    op.create_table(
        "connector_config",
        sa.Column("id",             UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name",           sa.String(255), nullable=False),
        sa.Column("connector_type", CONNECTOR_TYPE_ENUM, nullable=False),
        sa.Column("vault_path",     sa.String(512), nullable=False,
                  comment="Vault KV path where credentials are stored (TASK-US047-02)"),
        sa.Column("config",         JSONB, nullable=False, server_default="{}"),
        sa.Column("enabled",        sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by",     sa.String(255), nullable=False),
        sa.Column("created_at",     sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",     sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # updated_at auto-update requires a trigger; onupdate is ORM-side only
    )
    op.create_index("ix_connector_config_type",    "connector_config", ["connector_type"])
    op.create_index("ix_connector_config_enabled", "connector_config", ["enabled"])

    # -----------------------------------------------------------------------
    # Table 2: knowledge_source
    # -----------------------------------------------------------------------
    op.create_table(
        "knowledge_source",
        sa.Column("id",              UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("connector_id",    UUID(as_uuid=True), nullable=False),
        sa.Column("source_uri",      sa.Text(),     nullable=False),
        sa.Column("title",           sa.String(512), nullable=True),
        sa.Column("content_hash",    sa.String(64),  nullable=True,
                  comment="SHA-256 of raw content; used for dedup detection"),
        sa.Column("last_indexed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata",        JSONB, nullable=False, server_default="{}"),
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
        sa.Column("id",           UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id",    UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index",  sa.Integer(), nullable=False,
                  comment="Zero-based position of this chunk within the source document"),
        sa.Column("content",      sa.Text(),    nullable=False),
        sa.Column("token_count",  sa.Integer(), nullable=True),
        sa.Column("embedding_id", sa.String(128), nullable=True,
                  comment="Reference ID in Qdrant vector store"),
        sa.Column("metadata",     JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at",   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_source.id"],
            name="fk_knowledge_chunk_source", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_knowledge_chunk_source_idx"),
    )
    op.create_index("ix_knowledge_chunk_source_id",    "knowledge_chunk", ["source_id"])
    op.create_index("ix_knowledge_chunk_embedding_id", "knowledge_chunk", ["embedding_id"])

    # -----------------------------------------------------------------------
    # Table 4: model_registry_legacy
    #
    # NOTE: Named "model_registry_legacy" (not "model_registry") to avoid a
    # table-name collision with the actively-used model_registry table
    # created by migration 0010 (src/model_registry/models/model.py,
    # EP-006 Dynamic Model Routing). This table backs the unused ORM scaffold
    # at src/data/models/model_registry.py, which is not imported by any
    # active router/service/repository.
    # -----------------------------------------------------------------------
    op.create_table(
        "model_registry_legacy",
        sa.Column("id",                    UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id",              sa.String(255), nullable=False, unique=True,
                  comment="Canonical model identifier e.g. gpt-4o, claude-3-5-sonnet"),
        sa.Column("provider",              sa.String(128), nullable=False),
        sa.Column("display_name",          sa.String(255), nullable=False),
        sa.Column("context_window",        sa.Integer(),   nullable=False),
        sa.Column("cost_per_input_token",  sa.Numeric(18, 8), nullable=True),
        sa.Column("cost_per_output_token", sa.Numeric(18, 8), nullable=True),
        sa.Column("status",       MODEL_STATUS_ENUM, nullable=False, server_default="active"),
        sa.Column("capabilities", JSONB, nullable=False, server_default="{}",
                  comment='Feature flags e.g. {"tool_use": true, "vision": false}'),
        sa.Column("config",       JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at",   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_model_registry_legacy_provider", "model_registry_legacy", ["provider"])
    op.create_index("ix_model_registry_legacy_status",   "model_registry_legacy", ["status"])

    # -----------------------------------------------------------------------
    # Table 5: policy
    # -----------------------------------------------------------------------
    op.create_table(
        "policy",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name",        sa.String(255), nullable=False, unique=True),
        sa.Column("policy_type", POLICY_TYPE_ENUM, nullable=False),
        sa.Column("rules",       JSONB, nullable=False,
                  comment="Rego-compatible rule definition or routing weight map"),
        sa.Column("enabled",     sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("priority",    sa.Integer(), nullable=False, server_default="100",
                  comment="Evaluation order; lower number = higher priority"),
        sa.Column("created_by",  sa.String(255), nullable=False),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_policy_type",     "policy", ["policy_type"])
    op.create_index("ix_policy_enabled",  "policy", ["enabled"])
    op.create_index("ix_policy_priority", "policy", ["priority"])

    # -----------------------------------------------------------------------
    # Table 6: audit_log  (application-level; distinct from admin_audit_log in 0019)
    # -----------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id",            UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type",    sa.String(128), nullable=False),
        sa.Column("user_id",       sa.String(255), nullable=True),
        sa.Column("resource_type", sa.String(128), nullable=False),
        sa.Column("resource_id",   sa.String(255), nullable=True),
        sa.Column("details",       JSONB, nullable=False, server_default="{}"),
        sa.Column("ip_address",    sa.String(45),  nullable=True),
        sa.Column("user_agent",    sa.Text(),       nullable=True),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_user_id",    "audit_log", ["user_id"])
    op.create_index("ix_audit_log_resource",   "audit_log", ["resource_type", "resource_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    # BRIN index for efficient time-range scans on append-only audit records.
    # A partial index with `WHERE created_at > now()` is not allowed in PostgreSQL
    # because now() is STABLE not IMMUTABLE; BRIN achieves the same efficiency goal.
    op.create_index(
        "ix_audit_log_created_brin",
        "audit_log",
        ["created_at"],
        postgresql_using="brin",
    )

    # -----------------------------------------------------------------------
    # Table 7: execution_trace_index
    # -----------------------------------------------------------------------
    op.create_table(
        "execution_trace_index",
        sa.Column("id",            UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("trace_id",      sa.String(128), nullable=False, unique=True,
                  comment="OTLP trace ID — links to full trace in MinIO contextiq-traces bucket"),
        sa.Column("request_id",    sa.String(128), nullable=True),
        sa.Column("user_id",       sa.String(255), nullable=True),
        sa.Column("model_id",      sa.String(255), nullable=True),
        sa.Column("input_tokens",  sa.Integer(),   nullable=True),
        sa.Column("output_tokens", sa.Integer(),   nullable=True),
        sa.Column("latency_ms",    sa.Integer(),   nullable=True),
        sa.Column("error",         sa.Text(),      nullable=True),
        sa.Column("metadata",      JSONB, nullable=False, server_default="{}"),
        sa.Column("started_at",    sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at",   sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_exec_trace_trace_id",   "execution_trace_index", ["trace_id"])
    op.create_index("ix_exec_trace_user_id",    "execution_trace_index", ["user_id"])
    op.create_index("ix_exec_trace_model_id",   "execution_trace_index", ["model_id"])
    op.create_index("ix_exec_trace_started_at", "execution_trace_index", ["started_at"])

    # -----------------------------------------------------------------------
    # Table 8: sync_job
    # -----------------------------------------------------------------------
    op.create_table(
        "sync_job",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("connector_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status",       SYNC_STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("started_at",   sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at",  sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("items_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_log",    sa.Text(),    nullable=True),
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
    # Drop in reverse dependency order; indexes are dropped automatically with their tables
    op.drop_table("sync_job")
    op.drop_table("execution_trace_index")
    op.drop_table("audit_log")
    op.drop_table("policy")
    op.drop_table("model_registry_legacy")
    op.drop_table("knowledge_chunk")
    op.drop_table("knowledge_source")
    op.drop_table("connector_config")
    bind = op.get_bind()
    CONNECTOR_TYPE_ENUM.drop(bind, checkfirst=True)
    SYNC_STATUS_ENUM.drop(bind, checkfirst=True)
    POLICY_TYPE_ENUM.drop(bind, checkfirst=True)
    MODEL_STATUS_ENUM.drop(bind, checkfirst=True)
