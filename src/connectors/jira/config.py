"""
JiraConnectorConfig — settings for the Jira connector.

TASK-US024-01: Vault Auth, JiraConnectorConfig, and GrafanaConnectorConfig.

All fields may be overridden by environment variables prefixed with
``JIRA_CONNECTOR_``.  The ``vault_secret_id`` field is excluded from
``repr`` to prevent accidental credential leakage in logs.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JiraConnectorConfig(BaseSettings):
    """
    Configuration for the Jira connector.

    Supports independent enable/disable toggle (US-024 AC-5).
    """

    model_config = SettingsConfigDict(
        env_prefix="JIRA_CONNECTOR_",
        env_file=".env",
        extra="ignore",
    )

    enabled: bool = True
    base_url: str = ""  # e.g. "https://acme.atlassian.net"
    email: str = ""  # Jira Cloud basic auth email
    default_jql: str = 'project in ({projects}) AND status != "Done" ORDER BY updated DESC'
    projects: list[str] = Field(default_factory=list)  # e.g. ["OPS", "INFRA"]
    max_results: int = 50
    default_days: int = 30
    vault_path: str = "secret/data/jira/token"
    vault_role_id: str = ""
    vault_secret_id: str = Field(
        default="",
        repr=False,  # never emit AppRole secret_id in repr / logs
        description="HashiCorp Vault AppRole secret_id; injected at deploy time.",
    )
    vault_addr: str = "https://vault.internal:8200"
    request_timeout_s: float = 10.0
