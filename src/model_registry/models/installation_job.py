"""SQLAlchemy 2.x async ORM model for model_installation_jobs table.

Tracks background model installation/download operations with progress,
status, and error details.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Float, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.model_registry.models.base import Base


class ModelInstallationJob(Base):
    """ORM representation of the ``model_installation_jobs`` table.

    Tracks async model installation operations with status, progress, and error
    reporting for long-running downloads (especially Ollama models).

    Columns
    -------
    id                  : Primary key UUID, job identifier returned to client.
    model_id            : Target model identifier (e.g. 'ollama/llama3.2:3b').
    provider_type       : Provider type ('ollama', 'openai', etc.).
    status              : Current job status.
    progress_pct        : Download/installation progress (0-100).
    current_step        : Human-readable current operation.
    error_message       : Detailed error if status is 'failed'.
    request_params      : JSONB copy of original installation request.
    started_at          : Job start timestamp.
    completed_at        : Job completion timestamp (success or failure).
    created_by          : User ID who initiated the installation.
    """

    __tablename__ = "model_installation_jobs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    model_id: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        index=True,
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        server_default=text("'pending'"),
    )
    progress_pct: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default=text("0.0"),
    )
    current_step: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
