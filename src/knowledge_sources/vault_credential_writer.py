"""
VaultCredentialWriter — writes a connector credential to Vault on behalf of
the Admin Portal's "Add Connector" wizard.

Lets an operator paste a raw secret (e.g. a GitHub PAT) directly into the UI
instead of having to pre-populate Vault via the CLI. The secret is written
straight to Vault and is never persisted to PostgreSQL, logged, or echoed
back in any API response.

Security note: secret values are never logged. The synchronous ``hvac`` SDK
is wrapped in ``asyncio.to_thread()`` so it does not block the event loop.
"""
from __future__ import annotations

import asyncio

import hvac  # type: ignore[import-untyped]
import hvac.exceptions  # type: ignore[import-untyped]

from src.knowledge_sources.config import KnowledgeSourceSettings
from src.knowledge_sources.vault_validator import VaultValidationResult


class VaultCredentialWriter:
    """
    Writes a ``{"token": <value>}`` secret to a Vault KV v2 path using the
    platform's shared AppRole credentials.

    The writer **never raises** — all exceptions are caught and reflected in
    the returned :class:`VaultValidationResult`, mirroring
    :class:`~src.knowledge_sources.vault_validator.VaultPathValidator`.
    """

    def __init__(self, settings: KnowledgeSourceSettings | None = None) -> None:
        self._settings = settings or KnowledgeSourceSettings()

    async def write(self, vault_path: str, token: str) -> VaultValidationResult:
        """
        Write ``token`` to ``vault_path`` as a KV v2 secret.

        Returns:
            :class:`VaultValidationResult` with ``valid=True`` on success.
            Returns ``valid=False`` with a descriptive ``message`` (never
            including the secret value) on any failure. Never raises.
        """
        try:
            return await asyncio.to_thread(self._write_to_vault, vault_path, token)
        except Exception as exc:
            return VaultValidationResult(
                valid=False,
                message=f"Vault write error: {type(exc).__name__}: {str(exc)[:200]}",
            )

    def _write_to_vault(self, vault_path: str, token: str) -> VaultValidationResult:
        """Synchronous Vault write; must be called via ``asyncio.to_thread``."""
        client = hvac.Client(url=self._settings.vault_addr)

        try:
            client.auth.approle.login(
                role_id=self._settings.vault_role_id,
                secret_id=self._settings.vault_secret_id,
            )
        except Exception as exc:
            return VaultValidationResult(
                valid=False,
                message=(
                    "Vault authentication failed — check platform Vault credentials: "
                    f"{type(exc).__name__}"
                ),
            )

        try:
            client.secrets.kv.v2.create_or_update_secret(
                path=vault_path,
                secret={"token": token},
                mount_point=self._settings.vault_mount,
            )
            return VaultValidationResult(valid=True, message="Credential stored in Vault")
        except hvac.exceptions.Forbidden:
            return VaultValidationResult(
                valid=False,
                message=(
                    f"Vault path '{vault_path}' exists but platform role lacks "
                    "write permission"
                ),
            )
        except Exception as exc:
            return VaultValidationResult(
                valid=False,
                message=f"Vault write failed: {type(exc).__name__}: {str(exc)[:200]}",
            )
