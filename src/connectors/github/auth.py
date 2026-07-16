"""
GitHub token provider — retrieves a PAT or App installation token from Vault.

TASK-US022-01: GitHubConnectorConfig, Vault Token Provider, and authenticate().

Security note: token values are never logged.  The synchronous ``hvac`` SDK
is wrapped in ``asyncio.to_thread()`` so it does not block the event loop.
"""
from __future__ import annotations

import asyncio

import hvac  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connectors.github.config import GitHubConnectorConfig


class GitHubCredential(BaseModel):
    """Immutable credential container; never serialised or logged."""

    model_config = ConfigDict(frozen=True)

    token: str
    token_type: str  # "pat" | "app_installation"


class GitHubTokenProvider:
    """
    Retrieves a GitHub token from a HashiCorp Vault KV v2 path.

    The Vault client is created inside ``_read_from_vault()`` (not at module
    level) to avoid stale session handles across reconnects.
    """

    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def get_credential(self) -> GitHubCredential:
        """
        Read token from the configured Vault KV v2 path.

        Raises:
            ConnectorAuthError: when Vault returns an error or the secret is
                missing the required ``"token"`` key.  The original exception
                type is preserved as the ``__cause__``; the token value is
                never included in the error message.
        """
        try:
            credential = await asyncio.to_thread(self._read_from_vault)
        except ConnectorAuthError:
            raise
        except Exception as exc:
            raise ConnectorAuthError(
                f"Failed to retrieve GitHub token from Vault: {type(exc).__name__}"
            ) from exc
        return credential

    def _read_from_vault(self) -> GitHubCredential:
        """Synchronous Vault read; must be called via ``asyncio.to_thread``."""
        client = hvac.Client(url=self._config.vault_addr)
        client.auth.approle.login(
            role_id=self._config.vault_role_id,
            secret_id=self._config.vault_secret_id,
        )
        secret = client.secrets.kv.v2.read_secret_version(
            path=self._config.vault_path,
            mount_point="secret",
        )
        data: dict[str, str] = secret["data"]["data"]
        if "token" not in data:
            raise ConnectorAuthError("Vault secret missing 'token' key")
        token_type = data.get("token_type", "pat")
        return GitHubCredential(token=data["token"], token_type=token_type)
