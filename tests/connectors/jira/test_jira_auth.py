"""
Unit tests for TASK-US024-01: JiraConnectorConfig, JiraTokenProvider,
and JiraConnector.authenticate().

All Vault (hvac) calls are mocked via unittest.mock.patch; no live Vault in CI.

Coverage targets:
  - authenticate() sets self._credential to a JiraCredential with token and email
  - authenticate() raises ConnectorAuthError when Vault returns a non-200 response
  - authenticate() raises ConnectorAuthError when Vault secret is missing "token" key
  - authenticate() raises ConnectorAuthError when enabled=False
  - JiraConnectorConfig.vault_secret_id does not appear in repr(config)
  - _auth_headers() raises ConnectorAuthError before authenticate() is called
  - _auth_headers() returns Authorization: Basic <base64(email:token)>
  - Vault client is created inside _read_from_vault(), not as a module-level singleton
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connectors.jira.auth import JiraCredential, JiraTokenProvider
from src.connectors.jira.config import JiraConnectorConfig
from src.connectors.jira.connector import JiraConnector

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> JiraConnectorConfig:
    """Return a JiraConnectorConfig with test-safe defaults."""
    defaults: dict[str, object] = {
        "base_url": "https://acme.atlassian.net",
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "test-role-id",
        "vault_secret_id": "super-secret-value",
        "vault_path": "secret/data/jira/token",
        "email": "user@acme.com",
    }
    defaults.update(overrides)
    return JiraConnectorConfig.model_validate(defaults)


def _mock_vault_client(token: str = "jira_testtoken") -> MagicMock:  # noqa: S107
    """Return a mock hvac.Client that returns *token* from KV v2 read."""
    client = MagicMock()
    client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"token": token}}
    }
    return client


# ===========================================================================
# JiraConnectorConfig
# ===========================================================================


class TestJiraConnectorConfig:
    def test_vault_secret_id_hidden_in_repr(self) -> None:
        """AC: vault_secret_id must not appear in repr(config)."""
        config = _make_config()
        assert "super-secret-value" not in repr(config)

    def test_defaults(self) -> None:
        config = JiraConnectorConfig.model_validate(
            {"vault_role_id": "r", "vault_secret_id": "s"}
        )
        assert config.enabled is True
        assert config.max_results == 50
        assert config.default_days == 30
        assert config.projects == []
        assert config.vault_addr == "https://vault.internal:8200"
        assert config.vault_path == "connectors/jira/token"
        assert config.request_timeout_s == 10.0

    def test_enabled_false(self) -> None:
        config = _make_config(enabled=False)
        assert config.enabled is False

    def test_projects_list(self) -> None:
        config = _make_config(projects=["OPS", "INFRA"])
        assert config.projects == ["OPS", "INFRA"]


# ===========================================================================
# JiraCredential
# ===========================================================================


class TestJiraCredential:
    def test_frozen(self) -> None:
        cred = JiraCredential(token="tok", email="user@acme.com")  # noqa: S106
        with pytest.raises((TypeError, Exception)):
            cred.token = "other"  # type: ignore[misc]

    def test_fields(self) -> None:
        cred = JiraCredential(token="abc123", email="admin@test.com")  # noqa: S106
        assert cred.token == "abc123"
        assert cred.email == "admin@test.com"


# ===========================================================================
# JiraTokenProvider
# ===========================================================================


class TestJiraTokenProvider:
    async def test_get_credential_success(self) -> None:
        config = _make_config()
        provider = JiraTokenProvider(config)
        mock_client = _mock_vault_client("jira_abc")

        with patch("src.connectors.jira.auth.hvac.Client", return_value=mock_client):
            cred = await provider.get_credential()

        assert cred.token == "jira_abc"
        assert cred.email == "user@acme.com"
        mock_client.auth.approle.login.assert_called_once_with(
            role_id="test-role-id", secret_id="super-secret-value"
        )

    async def test_get_credential_missing_token_key(self) -> None:
        config = _make_config()
        provider = JiraTokenProvider(config)
        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {}}  # no "token" key
        }

        with patch("src.connectors.jira.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError, match="missing 'token' key"):
                await provider.get_credential()

    async def test_get_credential_vault_error_wrapped(self) -> None:
        config = _make_config()
        provider = JiraTokenProvider(config)
        mock_client = MagicMock()
        mock_client.auth.approle.login.side_effect = RuntimeError("connection refused")

        with patch("src.connectors.jira.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError, match="Jira Vault read failed"):
                await provider.get_credential()

    async def test_vault_client_created_per_call(self) -> None:
        """Vault client must be created inside _read_from_vault, not as singleton."""
        config = _make_config()
        provider = JiraTokenProvider(config)
        mock_client = _mock_vault_client()

        with patch("src.connectors.jira.auth.hvac.Client", return_value=mock_client) as mock_cls:
            await provider.get_credential()
            await provider.get_credential()

        assert mock_cls.call_count == 2


# ===========================================================================
# JiraConnector.authenticate()
# ===========================================================================


class TestJiraConnectorAuthenticate:
    async def test_authenticate_sets_credential(self) -> None:
        """AC: authenticate() sets self._credential to a JiraCredential."""
        config = _make_config()
        connector = JiraConnector(config)
        mock_client = _mock_vault_client("jira_secret_tok")

        with patch("src.connectors.jira.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        assert connector._credential is not None
        assert connector._credential.token == "jira_secret_tok"
        assert connector._credential.email == "user@acme.com"

    async def test_authenticate_disabled_raises(self) -> None:
        """AC: enabled=False causes authenticate() to raise ConnectorAuthError."""
        config = _make_config(enabled=False)
        connector = JiraConnector(config)

        with pytest.raises(ConnectorAuthError, match="disabled via config"):
            await connector.authenticate()

    async def test_authenticate_vault_failure_raises(self) -> None:
        config = _make_config()
        connector = JiraConnector(config)
        mock_client = MagicMock()
        mock_client.auth.approle.login.side_effect = Exception("vault unavailable")

        with patch("src.connectors.jira.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError):
                await connector.authenticate()


# ===========================================================================
# JiraConnector._auth_headers()
# ===========================================================================


class TestJiraConnectorAuthHeaders:
    def test_auth_headers_before_authenticate_raises(self) -> None:
        """AC: _auth_headers() raises ConnectorAuthError before authenticate()."""
        connector = JiraConnector(_make_config())
        with pytest.raises(ConnectorAuthError, match="authenticate\\(\\) has not been called"):
            connector._auth_headers()

    async def test_auth_headers_basic_base64(self) -> None:
        """AC: _auth_headers() returns Authorization: Basic <base64(email:token)>."""
        config = _make_config(email="admin@acme.com")
        connector = JiraConnector(config)
        mock_client = _mock_vault_client("mytoken123")

        with patch("src.connectors.jira.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        headers = connector._auth_headers()
        expected_b64 = base64.b64encode(b"admin@acme.com:mytoken123").decode()
        assert headers["Authorization"] == f"Basic {expected_b64}"
        assert headers["Accept"] == "application/json"
