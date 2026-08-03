"""
GitHubConnectorConfig — settings for the GitHub connector.

TASK-US022-01: GitHubConnectorConfig, Vault Token Provider, and authenticate().
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitHubConnectorConfig(BaseSettings):
    """
    Configuration for the GitHub connector.

    All fields may be overridden by environment variables prefixed with
    ``GITHUB_CONNECTOR_``.  The ``vault_secret_id`` field is excluded from
    ``repr`` to prevent accidental credential leakage in logs.
    """

    model_config = SettingsConfigDict(
        env_prefix="GITHUB_CONNECTOR_",
        env_file=".env",
        extra="ignore",
    )

    repos: list[str] = Field(
        default_factory=list,
        description="List of 'owner/repo' strings to index. Empty = all accessible repos.",
    )
    default_days: int = Field(
        default=30,
        description="Commit history look-back window in days (AC-4).",
    )
    base_url: str = "https://api.github.com"
    vault_path: str = "connectors/github/token"
    vault_role_id: str = ""
    vault_secret_id: str = Field(
        default="",
        repr=False,  # never emit AppRole secret_id in repr / logs
        description="HashiCorp Vault AppRole secret_id; injected at deploy time.",
    )
    vault_addr: str = "https://vault.internal:8200"
    request_timeout_s: float = 10.0
    fetch_timeout_s: float = Field(
        default=20.0,
        description=(
            "End-to-end timeout for a fetch, including search, branch-aware "
            "fallback discovery, and content enrichment."
        ),
    )
