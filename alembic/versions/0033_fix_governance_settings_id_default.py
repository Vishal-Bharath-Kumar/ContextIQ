"""fix governance_settings id default

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-29 00:00:01.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "governance_settings",
        "id",
        existing_type=sa.UUID(),
        server_default=sa.text("gen_random_uuid()"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "governance_settings",
        "id",
        existing_type=sa.UUID(),
        server_default=None,
        existing_nullable=False,
    )