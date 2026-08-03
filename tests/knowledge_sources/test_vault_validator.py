"""Unit tests for VaultPathValidator — TASK-US025-02.

All tests run without a live Vault server; ``hvac.Client`` is fully mocked.
The five branches covered:
  1. Successful path validation (valid=True)
  2. InvalidPath — path does not exist (valid=False)
  3. Forbidden — path exists but role lacks permission (valid=False)
  4. AppRole login failure (valid=False)
  5. Unexpected exception during metadata read (valid=False)

An additional assertion verifies that ``read_secret_metadata`` (not
``read_secret_version``) is called — confirming the lightweight metadata probe
is used rather than a full secret read.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import hvac.exceptions
import pytest

from src.knowledge_sources.config import KnowledgeSourceSettings
from src.knowledge_sources.vault_validator import VaultPathValidator, VaultValidationResult

VAULT_PATH = "contextiq/github/acme"
MOUNT = "secret"

_SETTINGS = KnowledgeSourceSettings(
    vault_addr="https://vault.test:8200",
    vault_role_id="test-role-id",
    vault_secret_id="test-secret-id",
    vault_mount=MOUNT,
)


def _make_client_mock(
    *,
    login_raises: Exception | None = None,
    metadata_raises: Exception | None = None,
) -> MagicMock:
    """Return a mock ``hvac.Client`` shaped like the real object."""
    client = MagicMock()

    if login_raises is not None:
        client.auth.approle.login.side_effect = login_raises
    else:
        client.auth.approle.login.return_value = {"auth": {"client_token": "tok"}}

    if metadata_raises is not None:
        client.secrets.kv.v2.read_secret_metadata.side_effect = metadata_raises
    else:
        client.secrets.kv.v2.read_secret_metadata.return_value = {
            "data": {"versions": {}}
        }

    return client


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestVaultPathValidatorSuccess:
    @pytest.mark.asyncio
    async def test_valid_path_returns_true(self) -> None:
        mock_client = _make_client_mock()
        with patch("src.knowledge_sources.vault_validator.hvac.Client", return_value=mock_client):
            validator = VaultPathValidator(settings=_SETTINGS)
            result = await validator.validate(VAULT_PATH)

        assert isinstance(result, VaultValidationResult)
        assert result.valid is True
        assert "exists" in result.message.lower()

    @pytest.mark.asyncio
    async def test_uses_read_secret_metadata_not_version(self) -> None:
        """Confirm the probe uses metadata endpoint, not secret-value endpoint."""
        mock_client = _make_client_mock()
        with patch("src.knowledge_sources.vault_validator.hvac.Client", return_value=mock_client):
            validator = VaultPathValidator(settings=_SETTINGS)
            await validator.validate(VAULT_PATH)

        mock_client.secrets.kv.v2.read_secret_metadata.assert_called_once_with(
            path=VAULT_PATH,
            mount_point=MOUNT,
        )
        mock_client.secrets.kv.v2.read_secret_version.assert_not_called()


# ---------------------------------------------------------------------------
# InvalidPath
# ---------------------------------------------------------------------------


class TestVaultPathValidatorInvalidPath:
    @pytest.mark.asyncio
    async def test_invalid_path_returns_false(self) -> None:
        mock_client = _make_client_mock(
            metadata_raises=hvac.exceptions.InvalidPath("not found")
        )
        with patch("src.knowledge_sources.vault_validator.hvac.Client", return_value=mock_client):
            validator = VaultPathValidator(settings=_SETTINGS)
            result = await validator.validate(VAULT_PATH)

        assert result.valid is False
        assert VAULT_PATH in result.message
        assert MOUNT in result.message
        assert "does not exist" in result.message


# ---------------------------------------------------------------------------
# Forbidden
# ---------------------------------------------------------------------------


class TestVaultPathValidatorForbidden:
    @pytest.mark.asyncio
    async def test_forbidden_returns_false(self) -> None:
        mock_client = _make_client_mock(
            metadata_raises=hvac.exceptions.Forbidden("403")
        )
        with patch("src.knowledge_sources.vault_validator.hvac.Client", return_value=mock_client):
            validator = VaultPathValidator(settings=_SETTINGS)
            result = await validator.validate(VAULT_PATH)

        assert result.valid is False
        assert "lacks read permission" in result.message


# ---------------------------------------------------------------------------
# AppRole login failure
# ---------------------------------------------------------------------------


class TestVaultPathValidatorLoginFailure:
    @pytest.mark.asyncio
    async def test_login_failure_returns_false(self) -> None:
        mock_client = _make_client_mock(
            login_raises=ConnectionError("vault unreachable")
        )
        with patch("src.knowledge_sources.vault_validator.hvac.Client", return_value=mock_client):
            validator = VaultPathValidator(settings=_SETTINGS)
            result = await validator.validate(VAULT_PATH)

        assert result.valid is False
        assert "authentication failed" in result.message.lower()
        assert "ConnectionError" in result.message

    @pytest.mark.asyncio
    async def test_login_failure_does_not_raise(self) -> None:
        mock_client = _make_client_mock(login_raises=RuntimeError("boom"))
        with patch("src.knowledge_sources.vault_validator.hvac.Client", return_value=mock_client):
            validator = VaultPathValidator(settings=_SETTINGS)
            result = await validator.validate(VAULT_PATH)  # must not raise

        assert result.valid is False


# ---------------------------------------------------------------------------
# Unexpected exception during metadata read
# ---------------------------------------------------------------------------


class TestVaultPathValidatorUnexpectedError:
    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_false(self) -> None:
        mock_client = _make_client_mock(
            metadata_raises=RuntimeError("internal error")
        )
        with patch("src.knowledge_sources.vault_validator.hvac.Client", return_value=mock_client):
            validator = VaultPathValidator(settings=_SETTINGS)
            result = await validator.validate(VAULT_PATH)

        assert result.valid is False
        assert "RuntimeError" in result.message

    @pytest.mark.asyncio
    async def test_validate_never_raises_on_outer_exception(self) -> None:
        """Even if asyncio.to_thread itself fails, validate() must not raise."""
        validator = VaultPathValidator(settings=_SETTINGS)
        with patch(
            "src.knowledge_sources.vault_validator.asyncio.to_thread",
            side_effect=RuntimeError("thread pool exhausted"),
        ):
            result = await validator.validate(VAULT_PATH)

        assert result.valid is False
        assert "RuntimeError" in result.message


# ---------------------------------------------------------------------------
# VaultValidationResult immutability
# ---------------------------------------------------------------------------


class TestVaultValidationResultImmutability:
    def test_result_is_frozen(self) -> None:
        result = VaultValidationResult(valid=True, message="ok")
        with pytest.raises((TypeError, ValueError)):
            result.valid = False  # type: ignore[misc]
