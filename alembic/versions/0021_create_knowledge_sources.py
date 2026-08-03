"""Create knowledge_sources table for EP-008 (Knowledge Source Management).

Revision ID: 0021a
Revises:     0022
Create Date: 2026-07-16

Creates the `knowledge_sources` table which stores connector registrations
managed via the Admin API (US-025).  This is distinct from the existing
`knowledge_source` table which tracks individual indexed documents.

NOTE: Revision id renumbered from "0021" to "0021a" to resolve a duplicate
revision-id collision with migration 0002_create_tool_registry.py (which
also claims revision "0021"). This migration is placed after 0022
(tool_connector_fk) instead of directly after 0020, since 0022's own chain
position is already fixed by 0023_create_sync_jobs.py's down_revision, and
sync_jobs.py has a hard FK dependency on knowledge_sources.id so this
migration must still run before it.

New PostgreSQL enum types introduced here:
  - ks_connector_type_enum  (github | confluence | jira | grafana)
  - source_status_enum      (active | inactive | syncing | error)

The `ks_` prefix on the connector enum avoids collision with the broader
`connector_type_enum` created in migration 0020.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision      = "0021a"
down_revision = "0022"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # NOTE: ks_connector_type_enum and source_status_enum are created
    # automatically by create_table() below (via the sa.Enum column
    # definitions) rather than via manual op.execute("CREATE TYPE ...")
    # calls — SQLAlchemy's create_type=False flag does not reliably suppress
    # duplicate creation unless checkfirst=True is also passed, so separate
    # manual CREATE TYPE statements would double-create them within this
    # same migration and fail.
    op.create_table(
        "knowledge_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "connector_type",
            sa.Enum("github", "confluence", "jira", "grafana", name="ks_connector_type_enum"),
            nullable=False,
        ),
        sa.Column("credentials_vault_path", sa.String(512), nullable=False),
        sa.Column("scope",                  sa.String(1024), nullable=False),
        sa.Column(
            "sync_schedule",
            sa.String(64),
            nullable=False,
            server_default="0 */6 * * *",
        ),
        sa.Column(
            "token_budget_weight",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "syncing", "error", name="source_status_enum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "last_sync_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "document_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Unique constraint: one registration per (connector_type, scope) pair
    op.create_index(
        "idx_knowledge_sources_connector_scope",
        "knowledge_sources",
        ["connector_type", "scope"],
        unique=True,
    )
    op.create_index(
        "idx_knowledge_sources_is_active",
        "knowledge_sources",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_sources")
    op.execute("DROP TYPE IF EXISTS source_status_enum")
    op.execute("DROP TYPE IF EXISTS ks_connector_type_enum")
