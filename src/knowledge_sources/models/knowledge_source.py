"""SQLAlchemy 2.x async ORM for the `knowledge_sources` table — TASK-US025-01.

This model is the data foundation for EP-008 (Knowledge Source Management &
Indexing).  The `knowledge_sources` table is distinct from the legacy
`knowledge_source` table in `src/data/models/knowledge_source.py` which
tracks individual indexed documents linked to a connector_config row.

The PostgreSQL enum types used here are:
  - `ks_connector_type_enum`  (github | confluence | jira | grafana)
  - `source_status_enum`      (active | inactive | syncing | error)

The prefix `ks_` avoids collision with the existing `connector_type_enum`
defined in migration 0020 which carries a broader set of connector values.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Float, Integer, String, text
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base

_KS_CONNECTOR_TYPE = PgEnum(
    "github", "confluence", "jira", "grafana",
    name="ks_connector_type_enum",
)
_SOURCE_STATUS = PgEnum(
    "active", "inactive", "syncing", "error",
    name="source_status_enum",
)


class KnowledgeSourceRecord(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connector_type: Mapped[str] = mapped_column(
        _KS_CONNECTOR_TYPE, nullable=False
    )
    credentials_vault_path: Mapped[str] = mapped_column(
        String(512), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(1024), nullable=False)
    sync_schedule: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="0 */6 * * *"
    )
    token_budget_weight: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("1.0")
    )
    status: Mapped[str] = mapped_column(
        _SOURCE_STATUS, nullable=False, server_default="active"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(nullable=True)
    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
