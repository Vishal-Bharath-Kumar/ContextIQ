"""create routing_weight_overrides

Revision ID: 0017
Revises:     0010
Create Date: 2026-07-18
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routing_weight_overrides",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("intent_type", sa.String(64), nullable=False),
        sa.Column("quality_weight", sa.Float(), nullable=False),
        sa.Column("cost_weight", sa.Float(), nullable=False),
        sa.Column("latency_weight", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.String(256), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_routing_weight_overrides_intent_type",
        "routing_weight_overrides",
        ["intent_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_routing_weight_overrides_intent_type")
    op.drop_table("routing_weight_overrides")
