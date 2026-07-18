"""Pydantic schemas for connector audit events and health-check — TASK-US039-04."""
from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventType(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    CONFIG_UPDATED = "config_updated"
    HEALTH_CHECKED = "health_checked"


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    connector_id: UUID
    event_type: AuditEventType
    actor_user_id: str  # sub claim from JWT
    detail: str | None = None  # human-readable summary


class HealthCheckResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    latency_ms: int
    detail: str | None = None  # error description when ok=False
