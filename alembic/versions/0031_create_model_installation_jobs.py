"""create model_installation_jobs table

Revision ID: 0031
Revises: 0030
Create Date: 2025-01-28 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0031'
down_revision: Union[str, None] = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create model_installation_jobs table for background installation tracking."""
    op.create_table(
        'model_installation_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('model_id', sa.String(length=256), nullable=False),
        sa.Column('provider_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('progress_pct', sa.Float(), server_default=sa.text('0.0'), nullable=False),
        sa.Column('current_step', sa.String(length=256), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('request_params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_model_installation_jobs_model_id'), 'model_installation_jobs', ['model_id'], unique=False)
    op.create_index(op.f('ix_model_installation_jobs_status'), 'model_installation_jobs', ['status'], unique=False)


def downgrade() -> None:
    """Drop model_installation_jobs table."""
    op.drop_index(op.f('ix_model_installation_jobs_status'), table_name='model_installation_jobs')
    op.drop_index(op.f('ix_model_installation_jobs_model_id'), table_name='model_installation_jobs')
    op.drop_table('model_installation_jobs')
