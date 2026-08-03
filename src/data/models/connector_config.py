from __future__ import annotations
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.base import Base


class ConnectorType(str, enum.Enum):
    CONFLUENCE  = "confluence"
    JIRA        = "jira"
    GITHUB      = "github"
    GITLAB      = "gitlab"
    SLACK       = "slack"
    SHAREPOINT  = "sharepoint"
    NOTION      = "notion"
    WEB_CRAWLER = "web_crawler"
    CUSTOM      = "custom"


class ConnectorConfig(Base):
    __tablename__ = "connector_config"

    id:             Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name:           Mapped[str]           = mapped_column(String(255), nullable=False)
    connector_type: Mapped[ConnectorType] = mapped_column(Enum(ConnectorType, name="connector_type_enum"), nullable=False)
    vault_path:     Mapped[str]           = mapped_column(String(512), nullable=False)
    config:         Mapped[dict]          = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    enabled:        Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by:     Mapped[str]           = mapped_column(String(255), nullable=False)
    created_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()"))

    knowledge_sources: Mapped[list[KnowledgeSource]] = relationship("KnowledgeSource", back_populates="connector", cascade="all, delete-orphan")
    sync_jobs:         Mapped[list[SyncJob]]          = relationship("SyncJob",          back_populates="connector", cascade="all, delete-orphan")


# Avoid circular import at module level; resolved at mapper configuration time
from src.data.models.knowledge_source import KnowledgeSource  # noqa: E402
from src.data.models.sync_job import SyncJob  # noqa: E402
