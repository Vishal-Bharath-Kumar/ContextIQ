"""
Grafana token provider — retrieves a service account token from Vault.

TASK-US024-01: Vault Auth, JiraConnectorConfig, and GrafanaConnectorConfig.

Security note: token values are never logged.  The synchronous ``hvac`` SDK
is wrapped in ``asyncio.to_thread()`` so it does not block the event loop.
"""
from __future__ import annotations

import asyncio

import hvac  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connectors.grafana.config import GrafanaConnectorConfig


class GrafanaCredential(BaseModel):
    """Immutable credential container; never serialised or logged."""

    model_config = ConfigDict(frozen=True)

    token: str  # Grafana service account token; used as Bearer


class GrafanaTokenProvider:
    """
    Retrieves a Grafana service account token from a HashiCorp Vault KV v2 path.

    The Vault client is created inside ``_read_from_vault()`` (not at module
    level) to avoid stale session handles across reconnects.
    """

    def __init__(self, config: GrafanaConnectorConfig) -> None:
        self._config = config

    async def get_credential(self) -> GrafanaCredential:
        """
        Read token from the configured Vault KV v2 path.

        Raises:
            ConnectorAuthError: when Vault returns an error or the secret is
                missing the required ``"token"`` key.  The original exception
                type is preserved as the ``__cause__``; the token value is
                never included in the error message.
        """
        try:
            return await asyncio.to_thread(self._read_from_vault)
        except ConnectorAuthError:
            raise
        except Exception as exc:
            raise ConnectorAuthError(
                f"Grafana Vault read failed: {type(exc).__name__}"
            ) from exc

    def _read_from_vault(self) -> GrafanaCredential:
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
        return GrafanaCredential(token=data["token"])
