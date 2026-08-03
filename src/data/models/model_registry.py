from __future__ import annotations
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Enum, Integer, Numeric, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class ModelStatus(str, enum.Enum):
    ACTIVE     = "active"
    DEPRECATED = "deprecated"
    RETIRED    = "retired"


class ModelRegistry(Base):
    # NOTE: table renamed from "model_registry" to "model_registry_legacy" to
    # avoid a name collision with the actively-used model_registry table
    # from src/model_registry/models/model.py (EP-006 Dynamic Model Routing,
    # migration 0010). This class is not imported by any active
    # router/service/repository — see alembic/versions/0020_create_core_app_tables.py.
    __tablename__ = "model_registry_legacy"

    id:                    Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    model_id:              Mapped[str]            = mapped_column(String(255), nullable=False, unique=True)
    provider:              Mapped[str]            = mapped_column(String(128), nullable=False)
    display_name:          Mapped[str]            = mapped_column(String(255), nullable=False)
    context_window:        Mapped[int]            = mapped_column(Integer, nullable=False)
    cost_per_input_token:  Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cost_per_output_token: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    status:                Mapped[ModelStatus]    = mapped_column(Enum(ModelStatus, name="model_status_enum"), nullable=False, default=ModelStatus.ACTIVE, server_default=text("'active'"))
    capabilities:          Mapped[dict]           = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    config:                Mapped[dict]           = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at:            Mapped[datetime]       = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at:            Mapped[datetime]       = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()"))
