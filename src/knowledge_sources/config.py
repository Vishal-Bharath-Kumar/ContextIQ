"""
KnowledgeSourceSettings — environment-driven configuration for the knowledge
source subsystem, including Vault connectivity for path validation.

TASK-US025-02: VaultPathValidator pre-creation Vault path verification.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeSourceSettings(BaseSettings):
    """
    Settings for the knowledge source subsystem.

    All fields may be overridden by environment variables prefixed with
    ``KNOWLEDGE_SOURCE_``.  ``vault_secret_id`` is excluded from ``repr``
    to prevent accidental credential leakage in logs.
    """

    model_config = SettingsConfigDict(
        env_prefix="KNOWLEDGE_SOURCE_",
        env_file=".env",
        extra="ignore",
    )

    vault_addr: str = "https://vault.internal:8200"
    vault_role_id: str = ""
    vault_secret_id: str = ""
    vault_mount: str = "secret"  # KV v2 mount name
