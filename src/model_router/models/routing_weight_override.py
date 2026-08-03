from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class RoutingWeightOverride(Base):
    __tablename__ = "routing_weight_overrides"
    __table_args__ = (
        UniqueConstraint("intent_type", name="uq_routing_weight_intent_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    intent_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quality_weight: Mapped[float] = mapped_column(Float, nullable=False)
    cost_weight: Mapped[float] = mapped_column(Float, nullable=False)
    latency_weight: Mapped[float] = mapped_column(Float, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
