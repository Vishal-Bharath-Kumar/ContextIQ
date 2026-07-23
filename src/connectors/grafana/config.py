"""
GrafanaConnectorConfig — settings for the Grafana connector.

TASK-US024-01: Vault Auth, JiraConnectorConfig, and GrafanaConnectorConfig.

All fields may be overridden by environment variables prefixed with
``GRAFANA_CONNECTOR_``.  The ``vault_secret_id`` field is excluded from
``repr`` to prevent accidental credential leakage in logs.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GrafanaConnectorConfig(BaseSettings):
    """
    Configuration for the Grafana connector.

    Supports independent enable/disable toggle (US-024 AC-5).
    """

    model_config = SettingsConfigDict(
        env_prefix="GRAFANA_CONNECTOR_",
        env_file=".env",
        extra="ignore",
    )

    enabled: bool = True
    base_url: str = ""  # e.g. "https://grafana.internal"
    dashboard_uids: list[str] = Field(default_factory=list)  # scope annotations to specific dashboards
    lookback_hours: int = 24  # annotation/alert history window
    max_results: int = 100
    vault_path: str = "connectors/grafana/token"
    vault_role_id: str = ""
    vault_secret_id: str = Field(
        default="",
        repr=False,  # never emit AppRole secret_id in repr / logs
        description="HashiCorp Vault AppRole secret_id; injected at deploy time.",
    )
    vault_addr: str = "https://vault.internal:8200"
    request_timeout_s: float = 10.0
