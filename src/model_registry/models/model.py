"""SQLAlchemy 2.x async ORM model for the model_registry table.

Provides the PostgreSQL source-of-truth for all registered AI models (TR-016).
Mirrors the six registration payload fields defined in ModelRegistration plus
audit columns.

TASK-US018-02 — EP-006 Dynamic Model Routing
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Float, Integer, String, text
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.model_registry.models.base import Base
from src.model_registry.schemas.model_definition import LatencyTier


class ModelRecord(Base):
    """ORM representation of the ``model_registry`` table (US-018 schema).

    Columns
    -------
    id                  : Primary key UUID, generated server-side.
    model_id            : Unique canonical identifier, e.g. ``gpt-4o-mini``.
    provider            : Hosting provider name, e.g. ``openai``.
    context_window      : Maximum token context window size.
    cost_per_1k_tokens  : USD cost per 1 000 combined tokens.
    latency_tier        : One of ``fast`` | ``medium`` | ``slow``.
    capabilities        : JSONB list of capability strings.
    is_active           : Soft-delete flag; defaults to ``true`` server-side.
    created_at          : Row creation timestamp (server default).
    updated_at          : Last-modified timestamp (server default + ORM onupdate).
    """

    __tablename__ = "model_registry"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    model_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_per_1k_tokens: Mapped[float] = mapped_column(Float, nullable=False)
    latency_tier: Mapped[str] = mapped_column(
        PgEnum(
            LatencyTier.FAST,
            LatencyTier.MEDIUM,
            LatencyTier.SLOW,
            name="latency_tier_enum",
        ),
        nullable=False,
    )
    capabilities: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
