"""
Unit tests for TASK-US023-01: ConfluenceConnectorConfig, Vault Token Provider,
and ConfluenceConnector.authenticate().

All Vault (hvac) calls are mocked via unittest.mock.patch; no live Vault in CI.

Coverage targets:
  - authenticate() sets self._credential to a ConfluenceCredential with a non-empty token
  - authenticate() raises ConnectorAuthError when Vault returns a non-200 response
  - authenticate() raises ConnectorAuthError when Vault secret is missing "token" key
  - ConfluenceConnectorConfig.vault_secret_id does not appear in repr(config)
  - _auth_headers() raises ConnectorAuthError before authenticate() is called
  - Cloud: _auth_headers() returns Authorization: Basic <base64(email:token)>
  - Data Center: _auth_headers() returns Authorization: Bearer <token>
  - Vault client is created inside _read_from_vault(), not as a module-level singleton
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connectors.confluence.auth import ConfluenceCredential, ConfluenceTokenProvider
from src.connectors.confluence.config import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connectors.confluence.connector import ConfluenceConnector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> ConfluenceConnectorConfig:
    """Return a ConfluenceConnectorConfig with test-safe defaults."""
    defaults: dict[str, object] = {
        "base_url": "https://acme.atlassian.net",
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "test-role-id",
        "vault_secret_id": "super-secret-value",
        "vault_path": "secret/data/confluence/token",
        "email": "user@acme.com",
    }
    defaults.update(overrides)
    return ConfluenceConnectorConfig.model_validate(defaults)


def _mock_vault_client(token: str = "conf_testtoken") -> MagicMock:  # noqa: S107
    """Return a mock hvac.Client that returns *token* from KV v2 read."""
    client = MagicMock()
    client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"token": token}}
    }
    return client


# ===========================================================================
# ConfluenceConnectorConfig
# ===========================================================================


class TestConfluenceConnectorConfig:
    def test_vault_secret_id_hidden_in_repr(self) -> None:
        """AC: vault_secret_id must not appear in repr(config)."""
        config = _make_config()
        assert "super-secret-value" not in repr(config)

    def test_defaults(self) -> None:
        config = ConfluenceConnectorConfig.model_validate(
            {"base_url": "https://acme.atlassian.net", "vault_role_id": "r", "vault_secret_id": "s"}
        )
        assert config.default_days == 30
        assert config.deployment_type == ConfluenceDeploymentType.CLOUD
        assert config.spaces == []
        assert config.vault_addr == "https://vault.internal:8200"

    def test_datacenter_deployment_type(self) -> None:
        config = _make_config(deployment_type="datacenter")
        assert config.deployment_type == ConfluenceDeploymentType.DATACENTER

    def test_spaces_list(self) -> None:
        config = _make_config(spaces=["~ENG", "ARCH"])
        assert config.spaces == ["~ENG", "ARCH"]


# ===========================================================================
# ConfluenceCredential
# ===========================================================================


class TestConfluenceCredential:
    def test_frozen(self) -> None:
        cred = ConfluenceCredential(
            token="tok",  # noqa: S106
            deployment_type=ConfluenceDeploymentType.CLOUD,
            email="user@acme.com",
        )
        with pytest.raises((TypeError, Exception)):
            cred.token = "other"  # type: ignore[misc]

    def test_cloud_email_populated(self) -> None:
        cred = ConfluenceCredential(
            token="tok",
            deployment_type=ConfluenceDeploymentType.CLOUD,
            email="user@acme.com",
        )
        assert cred.email == "user@acme.com"

    def test_datacenter_email_defaults_empty(self) -> None:
        cred = ConfluenceCredential(
            token="tok",
            deployment_type=ConfluenceDeploymentType.DATACENTER,
        )
        assert cred.email == ""


# ===========================================================================
# ConfluenceTokenProvider
# ===========================================================================


class TestConfluenceTokenProvider:
    @pytest.mark.asyncio
    async def test_get_credential_returns_credential(self) -> None:
        """AC: get_credential() returns a ConfluenceCredential with a non-empty token."""
        config = _make_config()
        mock_client = _mock_vault_client(token="conf_abc123")

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            provider = ConfluenceTokenProvider(config)
            cred = await provider.get_credential()

        assert isinstance(cred, ConfluenceCredential)
        assert cred.token == "conf_abc123"
        assert cred.deployment_type == ConfluenceDeploymentType.CLOUD
        assert cred.email == "user@acme.com"

    @pytest.mark.asyncio
    async def test_get_credential_uses_approle_login(self) -> None:
        """Vault AppRole login is called with the configured role_id and secret_id."""
        config = _make_config(vault_role_id="my-role", vault_secret_id="my-secret")
        mock_client = _mock_vault_client()

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            provider = ConfluenceTokenProvider(config)
            await provider.get_credential()

        mock_client.auth.approle.login.assert_called_once_with(
            role_id="my-role",
            secret_id="my-secret",
        )

    @pytest.mark.asyncio
    async def test_raises_connector_auth_error_on_vault_exception(self) -> None:
        """AC: raises ConnectorAuthError when Vault raises an exception."""
        config = _make_config()

        with patch(
            "src.connectors.confluence.auth.hvac.Client",
            side_effect=Exception("ConnectionError"),
        ):
            provider = ConfluenceTokenProvider(config)
            with pytest.raises(ConnectorAuthError, match="Failed to retrieve Confluence token"):
                await provider.get_credential()

    @pytest.mark.asyncio
    async def test_raises_connector_auth_error_on_login_failure(self) -> None:
        """AC: raises ConnectorAuthError when Vault login fails."""
        config = _make_config()
        mock_client = MagicMock()
        mock_client.auth.approle.login.side_effect = Exception("Forbidden")

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            provider = ConfluenceTokenProvider(config)
            with pytest.raises(ConnectorAuthError):
                await provider.get_credential()

    @pytest.mark.asyncio
    async def test_raises_connector_auth_error_when_token_key_missing(self) -> None:
        """AC: raises ConnectorAuthError when Vault secret is missing 'token' key."""
        config = _make_config()
        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"other_key": "value"}}  # 'token' key absent
        }

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            provider = ConfluenceTokenProvider(config)
            with pytest.raises(ConnectorAuthError, match="missing 'token' key"):
                await provider.get_credential()

    @pytest.mark.asyncio
    async def test_vault_client_created_per_call(self) -> None:
        """AC: Vault client is not a module-level singleton — a new Client is created each call."""
        config = _make_config()
        mock_client_a = _mock_vault_client(token="tok_a")
        mock_client_b = _mock_vault_client(token="tok_b")

        with patch(
            "src.connectors.confluence.auth.hvac.Client",
            side_effect=[mock_client_a, mock_client_b],
        ) as mock_cls:
            provider = ConfluenceTokenProvider(config)
            await provider.get_credential()
            await provider.get_credential()
            assert mock_cls.call_count == 2

    @pytest.mark.asyncio
    async def test_datacenter_credential_has_no_email(self) -> None:
        """Data Center credential carries empty email."""
        config = _make_config(deployment_type="datacenter", email="")
        mock_client = _mock_vault_client(token="pat_dc_token")

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            provider = ConfluenceTokenProvider(config)
            cred = await provider.get_credential()

        assert cred.deployment_type == ConfluenceDeploymentType.DATACENTER
        assert cred.email == ""


# ===========================================================================
# ConfluenceConnector
# ===========================================================================


class TestConfluenceConnector:
    @pytest.mark.asyncio
    async def test_authenticate_sets_credential(self) -> None:
        """AC: authenticate() sets self._credential to a ConfluenceCredential."""
        config = _make_config()
        connector = ConfluenceConnector(config=config)
        mock_client = _mock_vault_client(token="conf_success")

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        assert connector._credential is not None
        assert connector._credential.token == "conf_success"

    @pytest.mark.asyncio
    async def test_authenticate_raises_on_vault_error(self) -> None:
        """AC: authenticate() raises ConnectorAuthError when Vault returns non-200."""
        config = _make_config()
        connector = ConfluenceConnector(config=config)

        with patch(
            "src.connectors.confluence.auth.hvac.Client",
            side_effect=Exception("500 Internal Server Error"),
        ):
            with pytest.raises(ConnectorAuthError):
                await connector.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_raises_on_missing_token_key(self) -> None:
        """AC: authenticate() raises ConnectorAuthError when 'token' key is absent."""
        config = _make_config()
        connector = ConfluenceConnector(config=config)
        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {}}  # missing 'token'
        }

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError, match="missing 'token' key"):
                await connector.authenticate()

    # ------------------------------------------------------------------
    # _auth_headers — Cloud (Basic auth)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_auth_headers_cloud_basic_auth(self) -> None:
        """AC: Cloud _auth_headers() returns Authorization: Basic <base64(email:token)>."""
        config = _make_config(deployment_type="cloud", email="user@acme.com")
        connector = ConfluenceConnector(config=config)
        mock_client = _mock_vault_client(token="api_token_cloud")

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        headers = connector._auth_headers()
        expected_b64 = base64.b64encode(b"user@acme.com:api_token_cloud").decode()
        assert headers["Authorization"] == f"Basic {expected_b64}"
        assert headers["Accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_auth_headers_datacenter_bearer(self) -> None:
        """AC: Data Center _auth_headers() returns Authorization: Bearer <token>."""
        config = _make_config(deployment_type="datacenter", email="")
        connector = ConfluenceConnector(config=config)
        mock_client = _mock_vault_client(token="pat_bearer_token")

        with patch("src.connectors.confluence.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        headers = connector._auth_headers()
        assert headers["Authorization"] == "Bearer pat_bearer_token"
        assert headers["Accept"] == "application/json"

    def test_auth_headers_raises_before_authenticate(self) -> None:
        """AC: _auth_headers() raises ConnectorAuthError when called before authenticate()."""
        config = _make_config()
        connector = ConfluenceConnector(config=config)

        with pytest.raises(ConnectorAuthError, match="authenticate\\(\\) has not been called"):
            connector._auth_headers()
