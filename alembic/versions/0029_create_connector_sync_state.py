"""Create connector_sync_state table.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-22

Stores the last-sync-at cursor for each connector so incremental syncs
can look back only from the previous sync point (used by ConnectorSyncStore).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_sync_state",
        sa.Column("connector_id", sa.String(), nullable=False),
        sa.Column(
            "last_sync_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("connector_id", name="pk_connector_sync_state"),
    )


def downgrade() -> None:
    op.drop_table("connector_sync_state")
