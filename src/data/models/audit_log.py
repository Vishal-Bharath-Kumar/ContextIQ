from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id:            Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    event_type:    Mapped[str]         = mapped_column(String(128), nullable=False)
    user_id:       Mapped[str | None]  = mapped_column(String(255), nullable=True)
    resource_type: Mapped[str]         = mapped_column(String(128), nullable=False)
    resource_id:   Mapped[str | None]  = mapped_column(String(255), nullable=True)
    details:       Mapped[dict]        = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    ip_address:    Mapped[str | None]  = mapped_column(String(45), nullable=True)
    user_agent:    Mapped[str | None]  = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime]    = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
