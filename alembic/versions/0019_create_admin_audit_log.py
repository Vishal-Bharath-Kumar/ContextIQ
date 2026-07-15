"""create admin_audit_log with immutability trigger and SHA-256 hash chain

Revision ID: 0019
Revises:     None

BUG FIX (spec): the spec set down_revision = "0018", referencing
0018_create_model_audit_log which does not exist in this workspace.
Setting down_revision = None makes 0019 the chain root; once 0018 is
added it should be inserted between None and 0019 with its own
down_revision updated accordingly.

Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision      = "0019"
down_revision = None   # see module docstring
branch_labels = None
depends_on    = None

# ---------------------------------------------------------------------------
# PL/pgSQL trigger function — raises on any UPDATE or DELETE attempt (AC-2)
# ---------------------------------------------------------------------------
_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION admin_audit_log_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'admin_audit_log rows are immutable: UPDATE and DELETE are not permitted';
END;
$$;
"""

_TRIGGER = """
CREATE TRIGGER trg_admin_audit_log_immutable
BEFORE UPDATE OR DELETE ON admin_audit_log
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_immutability();
"""


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id",            sa.UUID(),                  primary_key=True),
        sa.Column("action",        sa.String(64),              nullable=False),
        sa.Column("resource_type", sa.String(64),              nullable=False),
        sa.Column("resource_id",   sa.String(256),             nullable=False),
        sa.Column("actor_user_id", sa.String(256),             nullable=False),
        sa.Column("ip_address",    sa.String(64),              nullable=False),
        sa.Column("before_state",  JSONB(),                    nullable=True),
        sa.Column("after_state",   JSONB(),                    nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("row_hash",      sa.String(64),              nullable=False),
    )
    op.create_index("ix_admin_audit_log_action",        "admin_audit_log", ["action"])
    op.create_index("ix_admin_audit_log_resource_type", "admin_audit_log", ["resource_type"])
    op.create_index("ix_admin_audit_log_resource_id",   "admin_audit_log", ["resource_id"])
    op.create_index("ix_admin_audit_log_actor_user_id", "admin_audit_log", ["actor_user_id"])
    op.create_index("ix_admin_audit_log_timestamp",     "admin_audit_log", ["timestamp"])

    # AC-2: immutability trigger — installed after table creation so that
    # the initial INSERT in upgrade() is not blocked.
    op.execute(_TRIGGER_FN)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_admin_audit_log_immutable ON admin_audit_log")
    op.execute("DROP FUNCTION IF EXISTS admin_audit_log_immutability")
    op.drop_table("admin_audit_log")
