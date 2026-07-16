"""Create sync_jobs table for EP-008 (Knowledge Source Sync Job Tracking).

Revision ID: 0023
Revises:     0022
Create Date: 2026-07-16

Creates the `sync_jobs` table which persists sync job lifecycle records for
each KnowledgeSource (US-026 AC-3).  The table is FK-linked to
`knowledge_sources.id` with CASCADE delete so that removing a source
automatically removes all its sync history.

New PostgreSQL enum type introduced here:
  - sync_job_status_enum  (running | succeeded | failed)
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE sync_job_status_enum AS ENUM ('running','succeeded','failed')"
    )
    op.create_table(
        "sync_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(name="sync_job_status_enum"),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "is_full_sync",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("items_processed", sa.Integer(), nullable=True),
        sa.Column("items_failed", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
    )
    op.create_index(
        "idx_sync_jobs_source_id_started",
        "sync_jobs",
        ["source_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_sync_jobs_source_id_started", table_name="sync_jobs")
    op.drop_table("sync_jobs")
    op.execute("DROP TYPE IF EXISTS sync_job_status_enum")
