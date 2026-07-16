"""
Unit tests for TASK-US024-01: GrafanaConnectorConfig, GrafanaTokenProvider,
and GrafanaConnector.authenticate().

All Vault (hvac) calls are mocked via unittest.mock.patch; no live Vault in CI.

Coverage targets:
  - authenticate() sets self._credential to a GrafanaCredential with token
  - authenticate() raises ConnectorAuthError when Vault returns a non-200 response
  - authenticate() raises ConnectorAuthError when Vault secret is missing "token" key
  - authenticate() raises ConnectorAuthError when enabled=False
  - GrafanaConnectorConfig.vault_secret_id does not appear in repr(config)
  - _auth_headers() raises ConnectorAuthError before authenticate() is called
  - _auth_headers() returns Authorization: Bearer <token>
  - Vault client is created inside _read_from_vault(), not as a module-level singleton
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connectors.grafana.auth import GrafanaCredential, GrafanaTokenProvider
from src.connectors.grafana.config import GrafanaConnectorConfig
from src.connectors.grafana.connector import GrafanaConnector

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> GrafanaConnectorConfig:
    """Return a GrafanaConnectorConfig with test-safe defaults."""
    defaults: dict[str, object] = {
        "base_url": "https://grafana.internal",
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "test-role-id",
        "vault_secret_id": "super-secret-value",
        "vault_path": "secret/data/grafana/token",
    }
    defaults.update(overrides)
    return GrafanaConnectorConfig.model_validate(defaults)


def _mock_vault_client(token: str = "glsa_testtoken") -> MagicMock:  # noqa: S107
    """Return a mock hvac.Client that returns *token* from KV v2 read."""
    client = MagicMock()
    client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"token": token}}
    }
    return client


# ===========================================================================
# GrafanaConnectorConfig
# ===========================================================================


class TestGrafanaConnectorConfig:
    def test_vault_secret_id_hidden_in_repr(self) -> None:
        """AC: vault_secret_id must not appear in repr(config)."""
        config = _make_config()
        assert "super-secret-value" not in repr(config)

    def test_defaults(self) -> None:
        config = GrafanaConnectorConfig.model_validate(
            {"vault_role_id": "r", "vault_secret_id": "s"}
        )
        assert config.enabled is True
        assert config.max_results == 100
        assert config.lookback_hours == 24
        assert config.dashboard_uids == []
        assert config.vault_addr == "https://vault.internal:8200"
        assert config.vault_path == "secret/data/grafana/token"
        assert config.request_timeout_s == 10.0

    def test_enabled_false(self) -> None:
        config = _make_config(enabled=False)
        assert config.enabled is False

    def test_dashboard_uids_list(self) -> None:
        config = _make_config(dashboard_uids=["abc123", "def456"])
        assert config.dashboard_uids == ["abc123", "def456"]


# ===========================================================================
# GrafanaCredential
# ===========================================================================


class TestGrafanaCredential:
    def test_frozen(self) -> None:
        cred = GrafanaCredential(token="tok")  # noqa: S106
        with pytest.raises((TypeError, Exception)):
            cred.token = "other"  # type: ignore[misc]

    def test_field(self) -> None:
        cred = GrafanaCredential(token="glsa_abc123")  # noqa: S106
        assert cred.token == "glsa_abc123"


# ===========================================================================
# GrafanaTokenProvider
# ===========================================================================


class TestGrafanaTokenProvider:
    async def test_get_credential_success(self) -> None:
        config = _make_config()
        provider = GrafanaTokenProvider(config)
        mock_client = _mock_vault_client("glsa_abc")

        with patch("src.connectors.grafana.auth.hvac.Client", return_value=mock_client):
            cred = await provider.get_credential()

        assert cred.token == "glsa_abc"
        mock_client.auth.approle.login.assert_called_once_with(
            role_id="test-role-id", secret_id="super-secret-value"
        )

    async def test_get_credential_missing_token_key(self) -> None:
        config = _make_config()
        provider = GrafanaTokenProvider(config)
        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {}}  # no "token" key
        }

        with patch("src.connectors.grafana.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError, match="missing 'token' key"):
                await provider.get_credential()

    async def test_get_credential_vault_error_wrapped(self) -> None:
        config = _make_config()
        provider = GrafanaTokenProvider(config)
        mock_client = MagicMock()
        mock_client.auth.approle.login.side_effect = RuntimeError("connection refused")

        with patch("src.connectors.grafana.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError, match="Grafana Vault read failed"):
                await provider.get_credential()

    async def test_vault_client_created_per_call(self) -> None:
        """Vault client must be created inside _read_from_vault, not as singleton."""
        config = _make_config()
        provider = GrafanaTokenProvider(config)
        mock_client = _mock_vault_client()

        with patch("src.connectors.grafana.auth.hvac.Client", return_value=mock_client) as mock_cls:
            await provider.get_credential()
            await provider.get_credential()

        assert mock_cls.call_count == 2


# ===========================================================================
# GrafanaConnector.authenticate()
# ===========================================================================


class TestGrafanaConnectorAuthenticate:
    async def test_authenticate_sets_credential(self) -> None:
        """AC: authenticate() sets self._credential to a GrafanaCredential."""
        config = _make_config()
        connector = GrafanaConnector(config)
        mock_client = _mock_vault_client("glsa_secret_tok")

        with patch("src.connectors.grafana.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        assert connector._credential is not None
        assert connector._credential.token == "glsa_secret_tok"

    async def test_authenticate_disabled_raises(self) -> None:
        """AC: enabled=False causes authenticate() to raise ConnectorAuthError."""
        config = _make_config(enabled=False)
        connector = GrafanaConnector(config)

        with pytest.raises(ConnectorAuthError, match="disabled via config"):
            await connector.authenticate()

    async def test_authenticate_vault_failure_raises(self) -> None:
        config = _make_config()
        connector = GrafanaConnector(config)
        mock_client = MagicMock()
        mock_client.auth.approle.login.side_effect = Exception("vault unavailable")

        with patch("src.connectors.grafana.auth.hvac.Client", return_value=mock_client):
            with pytest.raises(ConnectorAuthError):
                await connector.authenticate()


# ===========================================================================
# GrafanaConnector._auth_headers()
# ===========================================================================


class TestGrafanaConnectorAuthHeaders:
    def test_auth_headers_before_authenticate_raises(self) -> None:
        """AC: _auth_headers() raises ConnectorAuthError before authenticate()."""
        connector = GrafanaConnector(_make_config())
        with pytest.raises(ConnectorAuthError, match="authenticate\\(\\) has not been called"):
            connector._auth_headers()

    async def test_auth_headers_bearer(self) -> None:
        """AC: _auth_headers() returns Authorization: Bearer <token>."""
        config = _make_config()
        connector = GrafanaConnector(config)
        mock_client = _mock_vault_client("glsa_mytoken")

        with patch("src.connectors.grafana.auth.hvac.Client", return_value=mock_client):
            await connector.authenticate()

        headers = connector._auth_headers()
        assert headers["Authorization"] == "Bearer glsa_mytoken"
        assert headers["Accept"] == "application/json"
