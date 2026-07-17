"""Pydantic data-transfer objects for governance policy versioning.

Consumed by PolicyRepository (TASK-US033-02) and PolicyService (TASK-US033-03).
Audit fields (author, activated_at) satisfy AC-5.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyStatus(StrEnum):
    DRAFT = "draft"              # created, not yet active in OPA
    ACTIVE = "active"            # currently enforced by OPA
    SUPERSEDED = "superseded"    # previously active; replaced by newer version
    ROLLED_BACK = "rolled_back"  # was active, rolled back to a prior version


class PolicyCreate(BaseModel):
    """Payload for POST /v1/policies (AC-1)."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    version: str = Field(
        min_length=1,
        max_length=64,
        description="Semantic version string, e.g. '1.2.0'.",
    )
    rego_body: str = Field(
        min_length=1,
        description="Raw Rego source that will be pushed to OPA.",
    )


class PolicyVersion(BaseModel):
    """Read-only view of a single stored policy version (AC-2)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    policy_group: str             # logical name grouping all versions
    version: str
    description: str
    rego_body: str
    status: PolicyStatus
    author: str                   # sub claim from JWT (AC-5)
    activated_at: datetime | None = None  # populated on first activation (AC-5)
    created_at: datetime


class PolicySummary(BaseModel):
    """Compact view for list responses — excludes rego_body to keep response small."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    policy_group: str
    version: str
    description: str
    status: PolicyStatus
    author: str
    activated_at: datetime | None = None
    created_at: datetime


class ActivateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    activated_version: str
    bundle_push_ok: bool       # True if OPA accepted the bundle PUT
    activated_at: datetime


class RollbackResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    restored_version: str
    previous_active: str
    activated_at: datetime
