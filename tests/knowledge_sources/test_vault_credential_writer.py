"""Unit tests for VaultCredentialWriter.

All tests run without a live Vault server; ``hvac.Client`` is fully mocked.
Branches covered:
  1. Successful write (valid=True)
  2. Forbidden — path exists but role lacks write permission (valid=False)
  3. AppRole login failure (valid=False)
  4. Unexpected exception during the write call (valid=False)

An additional assertion verifies the secret is written via
``create_or_update_secret`` with a ``{"token": ...}`` payload and that the
raw token value never appears in the returned message.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import hvac.exceptions
import pytest

from src.knowledge_sources.config import KnowledgeSourceSettings
from src.knowledge_sources.vault_credential_writer import VaultCredentialWriter
from src.knowledge_sources.vault_validator import VaultValidationResult

VAULT_PATH = "connectors/github/my-org-pat"
MOUNT = "secret"
TOKEN = "ghp_super_secret_value_12345"

_SETTINGS = KnowledgeSourceSettings(
    vault_addr="https://vault.test:8200",
    vault_role_id="test-role-id",
    vault_secret_id="test-secret-id",
    vault_mount=MOUNT,
)


def _make_client_mock(
    *,
    login_raises: Exception | None = None,
    write_raises: Exception | None = None,
) -> MagicMock:
    """Return a mock ``hvac.Client`` shaped like the real object."""
    client = MagicMock()

    if login_raises is not None:
        client.auth.approle.login.side_effect = login_raises
    else:
        client.auth.approle.login.return_value = {"auth": {"client_token": "tok"}}

    if write_raises is not None:
        client.secrets.kv.v2.create_or_update_secret.side_effect = write_raises
    else:
        client.secrets.kv.v2.create_or_update_secret.return_value = {
            "data": {"version": 1}
        }

    return client


class TestVaultCredentialWriterSuccess:
    @pytest.mark.asyncio
    async def test_write_returns_true(self) -> None:
        mock_client = _make_client_mock()
        with patch(
            "src.knowledge_sources.vault_credential_writer.hvac.Client",
            return_value=mock_client,
        ):
            writer = VaultCredentialWriter(settings=_SETTINGS)
            result = await writer.write(VAULT_PATH, TOKEN)

        assert isinstance(result, VaultValidationResult)
        assert result.valid is True
        assert TOKEN not in result.message

    @pytest.mark.asyncio
    async def test_writes_token_key_to_correct_path_and_mount(self) -> None:
        mock_client = _make_client_mock()
        with patch(
            "src.knowledge_sources.vault_credential_writer.hvac.Client",
            return_value=mock_client,
        ):
            writer = VaultCredentialWriter(settings=_SETTINGS)
            await writer.write(VAULT_PATH, TOKEN)

        mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path=VAULT_PATH,
            secret={"token": TOKEN},
            mount_point=MOUNT,
        )


class TestVaultCredentialWriterForbidden:
    @pytest.mark.asyncio
    async def test_forbidden_returns_false_without_leaking_token(self) -> None:
        mock_client = _make_client_mock(
            write_raises=hvac.exceptions.Forbidden("403")
        )
        with patch(
            "src.knowledge_sources.vault_credential_writer.hvac.Client",
            return_value=mock_client,
        ):
            writer = VaultCredentialWriter(settings=_SETTINGS)
            result = await writer.write(VAULT_PATH, TOKEN)

        assert result.valid is False
        assert "lacks write permission" in result.message
        assert TOKEN not in result.message


class TestVaultCredentialWriterAuthFailure:
    @pytest.mark.asyncio
    async def test_login_failure_returns_false(self) -> None:
        mock_client = _make_client_mock(login_raises=RuntimeError("connection refused"))
        with patch(
            "src.knowledge_sources.vault_credential_writer.hvac.Client",
            return_value=mock_client,
        ):
            writer = VaultCredentialWriter(settings=_SETTINGS)
            result = await writer.write(VAULT_PATH, TOKEN)

        assert result.valid is False
        assert "Vault authentication failed" in result.message
        assert TOKEN not in result.message


class TestVaultCredentialWriterUnexpectedError:
    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_false(self) -> None:
        mock_client = _make_client_mock(write_raises=ValueError("boom"))
        with patch(
            "src.knowledge_sources.vault_credential_writer.hvac.Client",
            return_value=mock_client,
        ):
            writer = VaultCredentialWriter(settings=_SETTINGS)
            result = await writer.write(VAULT_PATH, TOKEN)

        assert result.valid is False
        assert TOKEN not in result.message
