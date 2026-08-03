"""
VaultPathValidator — verifies a Vault KV v2 path exists before a knowledge
source record is written to PostgreSQL.

TASK-US025-02: VaultPathValidator pre-creation Vault path verification (US-025 AC-5).

Security note: secret *values* are never read; only metadata is fetched so the
probe neither counts against ``max_uses`` nor appears as a secret-access in the
Vault audit log.  The synchronous ``hvac`` SDK is wrapped in
``asyncio.to_thread()`` so it does not block the event loop.
"""
from __future__ import annotations

import asyncio

import hvac  # type: ignore[import-untyped]
import hvac.exceptions  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from src.knowledge_sources.config import KnowledgeSourceSettings


class VaultValidationResult(BaseModel):
    """
    Immutable result returned by :class:`VaultPathValidator`.

    ``message`` is human-readable and surfaced directly as the ``detail``
    field of the HTTP 400 response when ``valid`` is ``False``.
    """

    model_config = ConfigDict(frozen=True)

    valid: bool
    message: str


class VaultPathValidator:
    """
    Pre-creation validator that confirms a Vault KV v2 path exists and is
    accessible with the platform's AppRole credentials.

    The validator **never raises** — all exceptions are caught and reflected
    in the returned :class:`VaultValidationResult`.
    """

    def __init__(self, settings: KnowledgeSourceSettings | None = None) -> None:
        self._settings = settings or KnowledgeSourceSettings()

    async def validate(self, vault_path: str) -> VaultValidationResult:
        """
        Confirm ``vault_path`` exists in Vault by reading its KV v2 metadata.

        Returns:
            :class:`VaultValidationResult` with ``valid=True`` when the path
            exists and the platform role has read permission.  Returns
            ``valid=False`` with a descriptive ``message`` on any failure.
            Never raises.
        """
        try:
            return await asyncio.to_thread(self._check_vault, vault_path)
        except Exception as exc:
            return VaultValidationResult(
                valid=False,
                message=f"Vault validation error: {type(exc).__name__}: {str(exc)[:200]}",
            )

    def _check_vault(self, vault_path: str) -> VaultValidationResult:
        """Synchronous Vault probe; must be called via ``asyncio.to_thread``."""
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
            # Read metadata only (not the secret value) to confirm the path
            # exists without consuming max_uses or triggering a secret-access
            # audit event.
            client.secrets.kv.v2.read_secret_metadata(
                path=vault_path,
                mount_point=self._settings.vault_mount,
            )
            return VaultValidationResult(valid=True, message="Vault path exists")
        except hvac.exceptions.InvalidPath:
            return VaultValidationResult(
                valid=False,
                message=(
                    f"Vault path '{vault_path}' does not exist in mount "
                    f"'{self._settings.vault_mount}'"
                ),
            )
        except hvac.exceptions.Forbidden:
            return VaultValidationResult(
                valid=False,
                message=(
                    f"Vault path '{vault_path}' exists but platform role lacks "
                    "read permission"
                ),
            )
        except Exception as exc:
            return VaultValidationResult(
                valid=False,
                message=(
                    f"Vault path check failed: {type(exc).__name__}: {str(exc)[:200]}"
                ),
            )
