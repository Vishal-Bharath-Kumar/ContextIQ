from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, TIMESTAMP, text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.base import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        UniqueConstraint("source_id", "chunk_index", name="uq_knowledge_chunk_source_idx"),
    )

    id:           Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    source_id:    Mapped[uuid.UUID]   = mapped_column(ForeignKey("knowledge_source.id", ondelete="CASCADE"), nullable=False)
    chunk_index:  Mapped[int]         = mapped_column(Integer, nullable=False)
    content:      Mapped[str]         = mapped_column(Text, nullable=False)
    token_count:  Mapped[int | None]  = mapped_column(Integer, nullable=True)
    embedding_id: Mapped[str | None]  = mapped_column(String(128), nullable=True)
    metadata:     Mapped[dict]        = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at:   Mapped[datetime]    = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    source: Mapped[KnowledgeSource] = relationship("KnowledgeSource", back_populates="chunks")


from src.data.models.knowledge_source import KnowledgeSource  # noqa: E402
