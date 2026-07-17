"""Create execution_traces table for EP-011 (AI Execution Replay).

Revision ID: 0026
Revises:     0025
Create Date: 2026-07-17

Creates the ``execution_traces`` table which persists searchable metadata for
every AI pipeline request (US-034 AC-4).  Full trace JSON is stored in MinIO;
this table is the PostgreSQL index for Replay Explorer (US-035) search filters.

Indexed on: timestamp, intent, (user_id, timestamp), (tenant_id, timestamp).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_traces",
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(256), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intent", sa.String(128), nullable=False),
        sa.Column("model_selected", sa.String(128), nullable=True),
        sa.Column(
            "governance_blocked",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "opa_denied_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column(
            "object_version",
            sa.String(256),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index("ix_traces_timestamp", "execution_traces", ["timestamp"])
    op.create_index("ix_traces_intent", "execution_traces", ["intent"])
    op.create_index(
        "ix_traces_user_timestamp", "execution_traces", ["user_id", "timestamp"]
    )
    op.create_index(
        "ix_traces_tenant_timestamp", "execution_traces", ["tenant_id", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_traces_tenant_timestamp", table_name="execution_traces")
    op.drop_index("ix_traces_user_timestamp", table_name="execution_traces")
    op.drop_index("ix_traces_intent", table_name="execution_traces")
    op.drop_index("ix_traces_timestamp", table_name="execution_traces")
    op.drop_table("execution_traces")
