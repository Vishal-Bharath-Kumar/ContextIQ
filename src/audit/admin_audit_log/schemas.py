"""
Pydantic schemas for the admin audit log — TASK-US044-01.

`AdminActionType` enumerates every mutating Admin API action (AC-1).
`AuditLogCreateRequest` is passed by route handlers to the repository.
`AuditLogEntry` is the API response DTO.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminActionType(StrEnum):
    # Policy lifecycle
    POLICY_CREATED          = "policy.created"
    POLICY_ACTIVATED        = "policy.activated"
    POLICY_ROLLED_BACK      = "policy.rolled_back"
    POLICY_DELETED          = "policy.deleted"

    # Connector lifecycle
    CONNECTOR_CREATED       = "connector.created"
    CONNECTOR_UPDATED       = "connector.updated"
    CONNECTOR_STATUS_CHANGED = "connector.status_changed"
    CONNECTOR_DELETED       = "connector.deleted"

    # Model registry
    MODEL_REGISTERED        = "model.registered"
    MODEL_STATUS_CHANGED    = "model.status_changed"
    MODEL_WEIGHTS_UPDATED   = "model.weights_updated"

    # RBAC / identity
    ROLE_ASSIGNED           = "role.assigned"
    ROLE_REVOKED            = "role.revoked"


class AuditLogCreateRequest(BaseModel):
    """Passed by route handlers to `AdminAuditRepository.log()`."""

    model_config = ConfigDict(frozen=True)

    action:        AdminActionType
    resource_type: str                       # e.g. "policy", "connector", "model"
    resource_id:   str                       # string to handle both UUID and string IDs
    actor_user_id: str                       # JWT `sub` claim
    ip_address:    str                       # from request.client.host (X-Forwarded-For preferred)
    before_state:  dict[str, Any] | None = None   # JSON snapshot before mutation
    after_state:   dict[str, Any] | None = None   # JSON snapshot after mutation


class AuditLogEntry(BaseModel):
    """API response DTO — returned from the audit log query endpoints."""

    model_config = ConfigDict(frozen=True)

    id:            UUID
    action:        AdminActionType
    resource_type: str
    resource_id:   str
    actor_user_id: str
    ip_address:    str
    before_state:  dict[str, Any] | None
    after_state:   dict[str, Any] | None
    timestamp:     datetime
    row_hash:      str    # SHA-256 of this row's content + previous row's hash (AC-6)
