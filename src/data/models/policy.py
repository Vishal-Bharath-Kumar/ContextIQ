from __future__ import annotations
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class PolicyType(str, enum.Enum):
    ROUTING        = "routing"
    ACCESS_CONTROL = "access_control"
    COST_LIMIT     = "cost_limit"
    RATE_LIMIT     = "rate_limit"


class Policy(Base):
    __tablename__ = "policy"

    id:          Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name:        Mapped[str]        = mapped_column(String(255), nullable=False, unique=True)
    policy_type: Mapped[PolicyType] = mapped_column(Enum(PolicyType, name="policy_type_enum"), nullable=False)
    rules:       Mapped[dict]       = mapped_column(JSONB, nullable=False)
    enabled:     Mapped[bool]       = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    priority:    Mapped[int]        = mapped_column(Integer, nullable=False, default=100, server_default=text("100"))
    created_by:  Mapped[str]        = mapped_column(String(255), nullable=False)
    created_at:  Mapped[datetime]   = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at:  Mapped[datetime]   = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()"))
