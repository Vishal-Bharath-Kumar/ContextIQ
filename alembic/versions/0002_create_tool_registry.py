"""Create tool_registry table.

Revision ID: 0021
Revises:     0020
Create Date: 2026-07-15

TASK-US002-02: source-of-truth table for MCP tool definitions.
Filename kept as 0002_create_tool_registry.py per task specification;
revision ID is 0021 to maintain sequential chain after 0020.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision      = "0021"
down_revision = "0020"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "tool_registry",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name",         sa.String(128), nullable=False),
        sa.Column("description",  sa.Text,        nullable=False),
        sa.Column(
            "input_schema",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "version",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'1.0.0'"),
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
        sa.UniqueConstraint("name", name="uq_tool_registry_name"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_tool_registry_status",
        ),
    )
    op.create_index("idx_tool_registry_status", "tool_registry", ["status"])


def downgrade() -> None:
    op.drop_index("idx_tool_registry_status", table_name="tool_registry")
    op.drop_table("tool_registry")
