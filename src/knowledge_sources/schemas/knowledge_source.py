"""Pydantic schemas for the knowledge_sources Admin API — TASK-US025-01.

`ConnectorType` and `SourceStatus` are the domain enums for the
`knowledge_sources` table (EP-008).  They are intentionally scoped to this
module and are distinct from the broader `ConnectorType` in
`src/data/models/connector_config.py` which drives the `connector_config` table.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ConnectorType(StrEnum):
    GITHUB     = "github"
    CONFLUENCE = "confluence"
    JIRA       = "jira"
    GRAFANA    = "grafana"


class SourceStatus(StrEnum):
    ACTIVE   = "active"    # indexed and eligible for retrieval
    INACTIVE = "inactive"  # registered but excluded from retrieval
    SYNCING  = "syncing"   # sync job currently in progress
    ERROR    = "error"     # last sync failed


class KnowledgeSourceCreate(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=255,
        description="Human-readable connector name shown in the Admin Portal.",
    )
    connector_type:          ConnectorType
    credentials_vault_path:  str = Field(
        min_length=1,
        max_length=512,
        description="Vault KV v2 path where connector credentials are stored",
    )
    credential_value: SecretStr | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
        description=(
            "Raw secret value (e.g. GitHub PAT) to write to "
            "credentials_vault_path in Vault on creation. Optional — omit if "
            "the secret already exists at that path. Never persisted to "
            "PostgreSQL or echoed back in any response."
        ),
    )
    scope: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "Connector-specific scope: 'owner/repo' for GitHub, "
            "'SPACE' for Confluence, etc."
        ),
    )
    sync_schedule: str = Field(
        default="0 */6 * * *",
        description="Cron expression for scheduled sync (UTC). Default: every 6 hours.",
    )
    token_budget_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Relative weight for token budget allocation across sources.",
    )

    @field_validator("sync_schedule")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError(
                "sync_schedule must be a 5-field cron expression (e.g. '0 */6 * * *')"
            )
        return v

    @field_validator("credentials_vault_path")
    @classmethod
    def validate_vault_path_format(cls, v: str) -> str:
        """Structural check only — live Vault validation is in VaultPathValidator."""
        if not re.match(r"^[a-zA-Z0-9/_\-\.]+$", v):
            raise ValueError("credentials_vault_path contains invalid characters")
        return v


class KnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                     UUID
    name:                   str | None
    connector_type:         ConnectorType
    credentials_vault_path: str
    scope:                  str
    sync_schedule:          str
    token_budget_weight:    float
    status:                 SourceStatus
    is_active:              bool
    last_sync_at:           datetime | None
    document_count:         int
    created_at:             datetime
    updated_at:             datetime
