"""Create policy_definitions table for EP-010 (Governance Engine & Policy Enforcement).

Revision ID: 0025
Revises:     0024
Create Date: 2026-07-17

Creates the ``policy_definitions`` table which persists every governance policy
version submitted to ContextIQ (US-033).  One row per (policy_group, version)
pair; at most one row per policy_group may hold status='active' at any time —
enforced at the service layer (TASK-US033-03).

Audit columns author and activated_at satisfy AC-5.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_group", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("rego_body", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("author", sa.String(256), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
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
