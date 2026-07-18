"""Create connector_audit_log table — TASK-US039-04.

Revision ID: 0027
Revises:     0026
Create Date: 2026-07-18
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_audit_log",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "connector_id",
            sa.UUID(),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.String(256), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_connector_audit_log_connector_id",
        "connector_audit_log",
        ["connector_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_audit_log_connector_id", table_name="connector_audit_log")
    op.drop_table("connector_audit_log")
