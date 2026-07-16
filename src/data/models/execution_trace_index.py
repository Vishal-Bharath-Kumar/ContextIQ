from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class ExecutionTraceIndex(Base):
    __tablename__ = "execution_trace_index"

    id:            Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    trace_id:      Mapped[str]              = mapped_column(String(128), nullable=False, unique=True)
    request_id:    Mapped[str | None]       = mapped_column(String(128), nullable=True)
    user_id:       Mapped[str | None]       = mapped_column(String(255), nullable=True)
    model_id:      Mapped[str | None]       = mapped_column(String(255), nullable=True)
    input_tokens:  Mapped[int | None]       = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None]       = mapped_column(Integer, nullable=True)
    latency_ms:    Mapped[int | None]       = mapped_column(Integer, nullable=True)
    error:         Mapped[str | None]       = mapped_column(Text, nullable=True)
    trace_metadata: Mapped[dict]             = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    started_at:    Mapped[datetime]         = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    finished_at:   Mapped[datetime | None]  = mapped_column(TIMESTAMP(timezone=True), nullable=True)
