"""Create chunk_index table for EP-008 (Knowledge Source Indexing).

Revision ID: 0024
Revises:     0023
Create Date: 2026-07-16

Creates the `chunk_index` table which persists per-chunk metadata after
successful embedding and vector-store upsert (US-027 AC-5).  The table is
used by the stale-embedding deletion path (AC-7) to identify and remove
chunks that belong to a document or source that no longer exists.

No FK constraint to `knowledge_sources.id` is created here; referential
integrity is enforced at the application layer to avoid lock contention at
high ingestion throughput (1 000 chunks/min target).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk_index",
        sa.Column("chunk_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("document_id", sa.String(512), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_chunk_index_source_id", "chunk_index", ["source_id"])
    op.create_index("ix_chunk_index_document_id", "chunk_index", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_chunk_index_document_id", table_name="chunk_index")
    op.drop_index("ix_chunk_index_source_id", table_name="chunk_index")
    op.drop_table("chunk_index")
