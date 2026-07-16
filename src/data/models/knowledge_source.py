from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.base import Base


class KnowledgeSource(Base):
    __tablename__ = "knowledge_source"

    id:              Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    connector_id:    Mapped[uuid.UUID]         = mapped_column(ForeignKey("connector_config.id", ondelete="CASCADE"), nullable=False)
    source_uri:      Mapped[str]               = mapped_column(Text, nullable=False)
    title:           Mapped[str | None]        = mapped_column(String(512), nullable=True)
    content_hash:    Mapped[str | None]        = mapped_column(String(64),  nullable=True)
    last_indexed_at: Mapped[datetime | None]   = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    source_metadata: Mapped[dict]              = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at:      Mapped[datetime]          = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    connector: Mapped[ConnectorConfig]         = relationship("ConnectorConfig", back_populates="knowledge_sources")
    chunks:    Mapped[list[KnowledgeChunk]]    = relationship("KnowledgeChunk", back_populates="source", cascade="all, delete-orphan")


from src.data.models.connector_config import ConnectorConfig  # noqa: E402
from src.data.models.knowledge_chunk import KnowledgeChunk    # noqa: E402
