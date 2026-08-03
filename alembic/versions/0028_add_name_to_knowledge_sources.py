"""Add name column to knowledge_sources — Admin Portal connector name display.

Revision ID: 0028
Revises:     0027
Create Date: 2026-07-22

The Add Connector wizard (frontend) always collected a display "name" for
each connector, but KnowledgeSourceCreate never had a matching field — the
value was silently dropped by pydantic's default "ignore extra fields"
behavior, so the Connectors list page's Name column was always blank.

Nullable so existing rows created before this fix don't need a backfill;
the API now requires `name` on every new POST /v1/knowledge-sources call.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_sources",
        sa.Column("name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_sources", "name")
