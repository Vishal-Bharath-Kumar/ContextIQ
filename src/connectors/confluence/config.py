"""
ConfluenceConnectorConfig — deployment-aware settings for the Confluence connector.

TASK-US023-01: ConfluenceConnectorConfig, Vault Token Provider, and authenticate().

Supports both Confluence Cloud (basic auth: email + API token) and
Confluence Data Center / Server (Bearer PAT).
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfluenceDeploymentType(StrEnum):
    """Distinguishes Confluence Cloud from Data Center / Server deployments."""

    CLOUD = "cloud"            # Confluence Cloud — auth via basic auth (email + API token)
    DATACENTER = "datacenter"  # Confluence Data Center / Server — auth via PAT (Bearer)


class ConfluenceConnectorConfig(BaseSettings):
    """
    Configuration for the Confluence connector.

    All fields may be overridden by environment variables prefixed with
    ``CONFLUENCE_CONNECTOR_``.  The ``vault_secret_id`` field is excluded from
    ``repr`` to prevent accidental credential leakage in logs.
    """

    model_config = SettingsConfigDict(
        env_prefix="CONFLUENCE_CONNECTOR_",
        env_file=".env",
        extra="ignore",
    )

    base_url: str  # e.g. "https://acme.atlassian.net" or "https://confluence.internal"
    deployment_type: ConfluenceDeploymentType = ConfluenceDeploymentType.CLOUD
    spaces: list[str] = Field(
        default_factory=list,
        description="Space keys to index, e.g. ['~ENG', 'ARCH']. Empty = all accessible spaces.",
    )
    email: str = ""  # Cloud only: user email for basic auth
    vault_path: str = "connectors/confluence/token"
    vault_role_id: str = ""
    vault_secret_id: str = Field(
        default="",
        repr=False,  # never emit AppRole secret_id in repr / logs
        description="HashiCorp Vault AppRole secret_id; injected at deploy time.",
    )
    vault_addr: str = "https://vault.internal:8200"
    request_timeout_s: float = 10.0
    default_days: int = 30  # lookback window in days for first sync
