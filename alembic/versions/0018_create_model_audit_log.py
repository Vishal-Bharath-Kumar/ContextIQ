"""create model_audit_log

Revision ID: 0018
Revises:     0017
Create Date: 2026-07-18
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_audit_log",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False),
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
    op.create_index("ix_model_audit_log_model_id", "model_audit_log", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_model_audit_log_model_id")
    op.drop_table("model_audit_log")
