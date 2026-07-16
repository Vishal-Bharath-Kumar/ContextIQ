"""
Unit tests for TASK-US022-01: GitHubConnectorConfig, Vault Token Provider,
and GitHubConnector.authenticate().

All Vault (hvac) calls are mocked via unittest.mock.patch; no live Vault in CI.

Coverage targets:
  - authenticate() sets self._credential to a GitHubCredential with a non-empty token
  - authenticate() raises ConnectorAuthError when Vault returns a non-200 response
  - authenticate() raises ConnectorAuthError when Vault secret is missing "token" key
  - GitHubConnectorConfig.vault_secret_id does not appear in repr(config)
  - _auth_header() raises ConnectorAuthError before authenticate() is called
  - Vault client is created inside _read_from_vault(), not as a module-level singleton
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.connector_sdk.exceptions import ConnectorAuthError  # noqa: E402
from src.connectors.github.auth import GitHubCredential, GitHubTokenProvider
from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.connector import GitHubConnector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides: object) -> GitHubConnectorConfig:
    """Return a GitHubConnectorConfig with test-safe defaults."""
    defaults = {
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "test-role-id",
        "vault_secret_id": "super-secret-value",
        "vault_path": "secret/data/github/token",
    }
    defaults.update(overrides)
    return GitHubConnectorConfig.model_validate(defaults)


def _mock_vault_client(token: str = "ghp_testtoken", token_type: str = "pat") -> MagicMock:  # noqa: S107
    """Return a mock hvac.Client that returns *token* from KV v2 read."""
    client = MagicMock()
    client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"token": token, "token_type": token_type}}
    }
    return client


# ===========================================================================
# GitHubConnectorConfig
# ===========================================================================

class TestGitHubConnectorConfig:
    def test_vault_secret_id_hidden_in_repr(self) -> None:
        """AC: vault_secret_id must not appear in repr(config)."""
        config = _make_config()
        assert "super-secret-value" not in repr(config)

    def test_defaults(self) -> None:
        config = GitHubConnectorConfig.model_validate(
            {"vault_role_id": "r", "vault_secret_id": "s"}
        )
        assert config.default_days == 30
        assert config.base_url == "https://api.github.com"
        assert config.repos == []

    def test_repos_list(self) -> None:
        config = _make_config(repos=["owner/repo-a", "owner/repo-b"])
        assert config.repos == ["owner/repo-a", "owner/repo-b"]


# ===========================================================================
# GitHubCredential
# ===========================================================================

class TestGitHubCredential:
    def test_frozen(self) -> None:
        cred = GitHubCredential(token="tok", token_type="pat")  # noqa: S106
        with pytest.raises((TypeError, Exception)):
            cred.token = "other"  # type: ignore[misc]

    def test_valid_token_types(self) -> None:
        for tt in ("pat", "app_installation"):
            cred = GitHubCredential(token="abc", token_type=tt)
            assert cred.token_type == tt


# ===========================================================================
# GitHubTokenProvider
# ===========================================================================

class TestGitHubTokenProvider:
    @pytest.mark.asyncio
    async def test_get_credential_returns_credential(self) -> None:
        """AC: authenticate() sets _credential to a GitHubCredential with a non-empty token."""
        config = _make_config()
        mock_client = _mock_vault_client(token="ghp_abc123")

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            provider = GitHubTokenProvider(config)
            cred = await provider.get_credential()

        assert isinstance(cred, GitHubCredential)
        assert cred.token == "ghp_abc123"
        assert cred.token_type == "pat"

    @pytest.mark.asyncio
    async def test_get_credential_uses_approle_login(self) -> None:
        """Vault AppRole login is called with the configured role_id and secret_id."""
        config = _make_config(vault_role_id="my-role", vault_secret_id="my-secret")
        mock_client = _mock_vault_client()

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            provider = GitHubTokenProvider(config)
            await provider.get_credential()

        mock_client.auth.approle.login.assert_called_once_with(
            role_id="my-role",
            secret_id="my-secret",
        )

    @pytest.mark.asyncio
    async def test_raises_connector_auth_error_on_vault_exception(self) -> None:
        """AC: authenticate() raises ConnectorAuthError when Vault returns an error."""
        config = _make_config()

        with patch(
            "src.connectors.github.auth.hvac.Client",
            side_effect=Exception("ConnectionError"),
        ):
            provider = GitHubTokenProvider(config)
            with pytest.raises(ConnectorAuthError, match="Failed to retrieve GitHub token"):
                await provider.get_credential()

    @pytest.mark.asyncio
    async def test_raises_connector_auth_error_on_login_failure(self) -> None:
        """AC: authenticate() raises ConnectorAuthError when Vault login fails."""
        config = _make_config()
        mock_client = MagicMock()
        mock_client.auth.approle.login.side_effect = Exception("Forbidden")

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            provider = GitHubTokenProvider(config)
            with pytest.raises(ConnectorAuthError):
                await provider.get_credential()

    @pytest.mark.asyncio
    async def test_raises_connector_auth_error_when_token_key_missing(self) -> None:
        """AC: authenticate() raises ConnectorAuthError when secret is missing 'token' key."""
        config = _make_config()
        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token_type": "pat"}}  # 'token' key absent
        }

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            provider = GitHubTokenProvider(config)
            with pytest.raises(ConnectorAuthError, match="missing 'token' key"):
                await provider.get_credential()

    @pytest.mark.asyncio
    async def test_vault_client_created_per_call(self) -> None:
        """AC: Vault client is not a module-level singleton — a new Client is created each call."""
        config = _make_config()
        mock_client_a = _mock_vault_client(token="tok_a")
        mock_client_b = _mock_vault_client(token="tok_b")

        with patch(
            "src.connectors.github.auth.hvac.Client",
            side_effect=[mock_client_a, mock_client_b],
        ) as mock_cls:
            provider = GitHubTokenProvider(config)
            await provider.get_credential()
            await provider.get_credential()
            assert mock_cls.call_count == 2


# ===========================================================================
# GitHubConnector
# ===========================================================================

class TestGitHubConnector:
    @pytest.mark.asyncio
    async def test_authenticate_sets_credential(self) -> None:
        """AC: authenticate() sets self._credential to a GitHubCredential."""
        config = _make_config()
        connector = GitHubConnector(config=config)
        mock_client = _mock_vault_client(token="ghp_success")

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        assert connector._credential is not None
        assert connector._credential.token == "ghp_success"

    @pytest.mark.asyncio
    async def test_authenticate_raises_on_vault_error(self) -> None:
        """AC: authenticate() raises ConnectorAuthError when Vault returns non-200."""
        config = _make_config()
        connector = GitHubConnector(config=config)

        with patch(
            "src.connectors.github.auth.hvac.Client",
            side_effect=Exception("500 Internal Server Error"),
        ):
            with pytest.raises(ConnectorAuthError):
                await connector.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_raises_on_missing_token_key(self) -> None:
        """AC: authenticate() raises ConnectorAuthError when 'token' key is absent."""
        config = _make_config()
        connector = GitHubConnector(config=config)
        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {}}  # missing 'token'
        }

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError, match="missing 'token' key"):
                await connector.authenticate()

    def test_auth_header_raises_before_authenticate(self) -> None:
        """AC: _auth_header() raises ConnectorAuthError when called before authenticate()."""
        connector = GitHubConnector(config=_make_config())
        with pytest.raises(ConnectorAuthError, match="authenticate\\(\\) has not been called"):
            connector._auth_header()

    @pytest.mark.asyncio
    async def test_auth_header_returns_bearer_token(self) -> None:
        """_auth_header() returns the correct Authorization header after authenticate()."""
        config = _make_config()
        connector = GitHubConnector(config=config)
        mock_client = _mock_vault_client(token="ghp_bearer")

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        headers = connector._auth_header()
        assert headers == {"Authorization": "Bearer ghp_bearer"}

    @pytest.mark.asyncio
    async def test_credential_cached_after_authenticate(self) -> None:
        """Credential is cached: a second call to _auth_header() reuses the same token."""
        config = _make_config()
        connector = GitHubConnector(config=config)
        mock_client = _mock_vault_client(token="ghp_cached")

        with patch("src.connectors.github.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        h1 = connector._auth_header()
        h2 = connector._auth_header()
        assert h1 == h2
