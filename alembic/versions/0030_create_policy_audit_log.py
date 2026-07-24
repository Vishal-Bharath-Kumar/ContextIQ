"""Create policy_audit_log table.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-24

Creates the ``policy_audit_log`` table for tracking policy lifecycle events
(create, activate, rollback). Append-only with immutability enforced by trigger.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

# PL/pgSQL trigger function — raises on any UPDATE or DELETE attempt
_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION policy_audit_log_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'policy_audit_log rows are immutable: UPDATE and DELETE are not permitted';
END;
$$;
"""

_TRIGGER = """
CREATE TRIGGER trg_policy_audit_log_immutable
BEFORE UPDATE OR DELETE ON policy_audit_log
FOR EACH ROW EXECUTE FUNCTION policy_audit_log_immutability();
"""


def upgrade() -> None:
    op.create_table(
        "policy_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.String(256), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    
    op.create_index(
        "ix_policy_audit_log_policy_id",
        "policy_audit_log",
        ["policy_id"],
    )
    op.create_index(
        "ix_policy_audit_log_event_type",
        "policy_audit_log",
        ["event_type"],
    )
    op.create_index(
        "ix_policy_audit_log_created_at",
        "policy_audit_log",
        ["created_at"],
    )
    
    # Install immutability trigger
    op.execute(_TRIGGER_FN)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_policy_audit_log_immutable ON policy_audit_log")
    op.execute("DROP FUNCTION IF EXISTS policy_audit_log_immutability")
    op.drop_table("policy_audit_log")
