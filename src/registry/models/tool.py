"""
SQLAlchemy ORM model for the tool_registry table.

TASK-US002-02: source-of-truth for MCP tool definitions.
TASK-US002-04: connector_id FK enables filtering tools by connector status.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.base import Base


class ToolStatus(str, enum.Enum):
    ACTIVE   = "active"
    INACTIVE = "inactive"


class Tool(Base):
    __tablename__ = "tool_registry"

    id:           Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name:         Mapped[str]               = mapped_column(String(128), nullable=False, unique=True)
    description:  Mapped[str]               = mapped_column(Text, nullable=False)
    input_schema: Mapped[dict]              = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    status:       Mapped[str]               = mapped_column(String(16), nullable=False, default=ToolStatus.ACTIVE, server_default=text("'active'"))
    version:      Mapped[str]               = mapped_column(String(32), nullable=False, default="1.0.0", server_default=text("'1.0.0'"))
    connector_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connector_config.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at:   Mapped[datetime]          = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at:   Mapped[datetime]          = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    connector: Mapped[Optional["ConnectorConfig"]] = relationship(  # type: ignore[name-defined]
        "ConnectorConfig",
        foreign_keys=[connector_id],
        lazy="noload",
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_tool_registry_status"),
    )


from src.data.models.connector_config import ConnectorConfig  # noqa: E402
