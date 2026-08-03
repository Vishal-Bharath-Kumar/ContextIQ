"""Add connector_id FK to tool_registry.

Revision ID: 0022
Revises:     0021
Create Date: 2026-07-15

TASK-US002-04: Links each tool to the connector that registered it.
Nullable so that platform-native (connector-independent) tools are unaffected.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision      = "0022"
down_revision = "0021"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        "tool_registry",
        sa.Column(
            "connector_id",
            UUID(as_uuid=True),
            sa.ForeignKey("connector_config.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_tool_registry_connector_id",
        "tool_registry",
        ["connector_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_tool_registry_connector_id", table_name="tool_registry")
    op.drop_column("tool_registry", "connector_id")
