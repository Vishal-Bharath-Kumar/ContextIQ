"""Create model_registry table for US-018 Dynamic Model Routing.

Revision ID: 0010
Revises:     None
Create Date: 2026-07-18

TASK-US018-02 — EP-006 Dynamic Model Routing.

This migration is the standalone schema root for the model_registry table
as defined by US-018.  It creates the ``latency_tier_enum`` PostgreSQL type
and the ``model_registry`` table with the six registration payload fields
plus audit columns.

NOTE: The revision chain root is ``None`` because migration ``0009`` has not
yet been committed to this workspace.  When ``0009`` is added, update
``down_revision`` to ``"0009"`` accordingly.

Index rationale
---------------
uq_model_registry_model_id
    Enforces the duplicate-registration constraint at the DB level (backs the
    409 check in the POST /v1/models handler).

idx_model_registry_is_active_cost
    Covers ``WHERE is_active = true ORDER BY cost_per_1k_tokens ASC`` used by
    the ``GET /v1/models`` list endpoint for cheapest-first ordering.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0010"
down_revision = None  # update to "0009" once that migration exists
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE latency_tier_enum AS ENUM ('fast', 'medium', 'slow')"
    )
    op.create_table(
        "model_registry",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("cost_per_1k_tokens", sa.Float(), nullable=False),
        sa.Column(
            "latency_tier",
            sa.Enum("fast", "medium", "slow", name="latency_tier_enum"),
            nullable=False,
        ),
        sa.Column(
            "capabilities",
            JSONB(),
            nullable=False,
            server_default="'[]'::jsonb",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
    op.create_unique_constraint(
        "uq_model_registry_model_id",
        "model_registry",
        ["model_id"],
    )
    op.create_index(
        "idx_model_registry_is_active_cost",
        "model_registry",
        ["is_active", "cost_per_1k_tokens"],
    )


def downgrade() -> None:
    op.drop_index("idx_model_registry_is_active_cost", table_name="model_registry")
    op.drop_constraint("uq_model_registry_model_id", "model_registry", type_="unique")
    op.drop_table("model_registry")
    op.execute("DROP TYPE latency_tier_enum")
