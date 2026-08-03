"""
Contract test suite for TASK-US023-05:
  - TestConfluenceConnector          — Cloud path, 6 BaseConnectorTestCase contracts
  - TestConfluenceConnectorDataCenter — DC Bearer-auth + URL-prefix validation
  - TestConfluenceConnectorBenchmark  — fetch() mocked mean < 2 s

All HTTP calls are intercepted by respx; no live Confluence or Vault in CI.
"""
from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.sync import SyncResult
from src.connector_sdk.testing import BaseConnectorTestCase
from src.connectors.confluence.auth import ConfluenceCredential
from src.connectors.confluence.config import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connectors.confluence.connector import ConfluenceConnector

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

CLOUD_CONFIG = ConfluenceConnectorConfig(
    base_url="https://acme.atlassian.net",
    deployment_type=ConfluenceDeploymentType.CLOUD,
    spaces=["ENG"],
    email="bot@acme.com",
    vault_role_id="test-role",
    vault_secret_id="test-secret",
)
DC_CONFIG = CLOUD_CONFIG.model_copy(
    update={
        "base_url": "https://confluence.internal",
        "deployment_type": ConfluenceDeploymentType.DATACENTER,
        "email": "",
    }
)

MOCK_CLOUD_CREDENTIAL = ConfluenceCredential(
    token="cloud-api-token",
    deployment_type=ConfluenceDeploymentType.CLOUD,
    email="bot@acme.com",
)
MOCK_DC_CREDENTIAL = ConfluenceCredential(
    token="datacenter-pat",
    deployment_type=ConfluenceDeploymentType.DATACENTER,
    email="",
)

MOCK_SEARCH_RESPONSE: dict[str, Any] = {
    "results": [
        {
            "id": "123456",
            "title": "Auth Flow",
            "space": {"key": "ENG"},
            "_links": {"webui": "/spaces/ENG/pages/123456/Auth+Flow"},
            "body": {"storage": {"value": "<p>Auth flow docs.</p>"}},
            "history": {
                "lastUpdated": {
                    "when": "2026-06-01T10:00:00.000Z",
                    "by": {"displayName": "Alice"},
                }
            },
        }
    ],
    "size": 1,
}

EMPTY_SEARCH_RESPONSE: dict[str, Any] = {"results": [], "size": 0}

# ---------------------------------------------------------------------------
# Vault mock fixtures
# ---------------------------------------------------------------------------

_VAULT_TARGET = "src.connectors.confluence.connector.ConfluenceTokenProvider.get_credential"


@pytest.fixture
def mock_vault_cloud() -> Generator[None, None, None]:
    with patch(_VAULT_TARGET, new_callable=AsyncMock, return_value=MOCK_CLOUD_CREDENTIAL):
        yield


@pytest.fixture
def mock_vault_dc() -> Generator[None, None, None]:
    with patch(_VAULT_TARGET, new_callable=AsyncMock, return_value=MOCK_DC_CREDENTIAL):
        yield


# ---------------------------------------------------------------------------
# Cloud contract tests
# ---------------------------------------------------------------------------


class TestConfluenceConnector(BaseConnectorTestCase):
    """6 SDK contract tests for the Confluence Cloud deployment path."""

    @pytest.fixture
    def make_connector(self, mock_vault_cloud: None) -> ConfluenceConnector:
        return ConfluenceConnector(config=CLOUD_CONFIG)

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        return ConnectorQuery(query="auth flow", max_results=5)

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
        sample_query: ConnectorQuery,
        mock_vault_cloud: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/wiki/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert results
        assert results[0].metadata.extra["space_key"] == "ENG"
        assert results[0].metadata.author == "Alice"

    @respx.mock
    async def test_fetch_respects_max_results(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
        sample_query: ConnectorQuery,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/wiki/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert len(results) <= sample_query.max_results

    @respx.mock
    async def test_sync_returns_sync_result(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/wiki/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=EMPTY_SEARCH_RESPONSE)
        )
        with (
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore.get_last_sync_at",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore.set_last_sync_at",
                new_callable=AsyncMock,
            ),
            patch(
                "src.connectors.confluence.connector.ConfluenceConnector._emit_sync_event",
                new_callable=AsyncMock,
            ),
        ):
            result = await make_connector.sync()
            assert isinstance(result, SyncResult)
            assert result.items_processed >= 0
            assert result.items_failed >= 0
            assert isinstance(result.last_sync_at, datetime)

    async def test_health_check_returns_health_status(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        status = await make_connector.health_check()
        assert isinstance(status, HealthStatus)
        assert isinstance(status.healthy, bool)
        assert isinstance(status.message, str)
        assert len(status.message) <= 200
        assert isinstance(status.checked_at, datetime)

    async def test_health_check_does_not_raise_on_repeated_calls(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        for _ in range(3):
            status = await make_connector.health_check()
            assert isinstance(status, HealthStatus)

    # ------------------------------------------------------------------
    # Targeted health_check behaviour tests
    # ------------------------------------------------------------------

    async def test_health_check_unauthenticated_returns_false(
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        status = await make_connector.health_check()
        assert status.healthy is False
        assert "authenticate" in status.message

    @respx.mock
    async def test_health_check_cloud_200_returns_true(
        self,
        make_connector: ConfluenceConnector,
        mock_vault_cloud: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/wiki/rest/api/space").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        status = await make_connector.health_check()
        assert status.healthy is True
        assert "acme.atlassian.net" in status.message

    @respx.mock
    async def test_health_check_cloud_401_returns_false(
        self,
        make_connector: ConfluenceConnector,
        mock_vault_cloud: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/wiki/rest/api/space").mock(
            return_value=httpx.Response(401)
        )
        status = await make_connector.health_check()
        assert status.healthy is False
        assert "401" in status.message

    @respx.mock
    async def test_health_check_connection_error_returns_false(
        self,
        make_connector: ConfluenceConnector,
        mock_vault_cloud: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/wiki/rest/api/space").mock(
            side_effect=httpx.ConnectError("refused")
        )
        status = await make_connector.health_check()
        assert status.healthy is False
        assert status.message != ""


# ---------------------------------------------------------------------------
# Data Center contract tests
# ---------------------------------------------------------------------------


class TestConfluenceConnectorDataCenter(BaseConnectorTestCase):
    """Validates Data Center deployment path — Bearer auth + different URL prefix."""

    @pytest.fixture
    def make_connector(self, mock_vault_dc: None) -> ConfluenceConnector:
        return ConfluenceConnector(config=DC_CONFIG)

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        return ConnectorQuery(query="runbook", max_results=3)

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
        sample_query: ConnectorQuery,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://confluence.internal/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=EMPTY_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert isinstance(results, list)

    @respx.mock
    async def test_fetch_respects_max_results(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
        sample_query: ConnectorQuery,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://confluence.internal/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=EMPTY_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert len(results) <= sample_query.max_results

    @respx.mock
    async def test_dc_uses_bearer_auth(
        self,
        make_connector: ConfluenceConnector,
        sample_query: ConnectorQuery,
    ) -> None:
        await make_connector.authenticate()
        route = respx.get("https://confluence.internal/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=EMPTY_SEARCH_RESPONSE)
        )
        await make_connector.fetch(sample_query)
        assert "Bearer" in route.calls.last.request.headers["authorization"]

    @respx.mock
    async def test_health_check_dc_200_returns_true(
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://confluence.internal/rest/api/space").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        status = await make_connector.health_check()
        assert status.healthy is True

    @respx.mock
    async def test_sync_returns_sync_result(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://confluence.internal/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=EMPTY_SEARCH_RESPONSE)
        )
        with (
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore.get_last_sync_at",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore.set_last_sync_at",
                new_callable=AsyncMock,
            ),
            patch(
                "src.connectors.confluence.connector.ConfluenceConnector._emit_sync_event",
                new_callable=AsyncMock,
            ),
        ):
            result = await make_connector.sync()
            assert isinstance(result, SyncResult)
            assert result.items_processed >= 0
            assert result.items_failed >= 0
            assert isinstance(result.last_sync_at, datetime)

    async def test_health_check_returns_health_status(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        status = await make_connector.health_check()
        assert isinstance(status, HealthStatus)
        assert isinstance(status.healthy, bool)
        assert isinstance(status.message, str)
        assert len(status.message) <= 200
        assert isinstance(status.checked_at, datetime)

    async def test_health_check_does_not_raise_on_repeated_calls(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        for _ in range(3):
            status = await make_connector.health_check()
            assert isinstance(status, HealthStatus)

    async def test_authenticate_does_not_raise(  # type: ignore[override]
        self,
        make_connector: ConfluenceConnector,
    ) -> None:
        await make_connector.authenticate()


# ---------------------------------------------------------------------------
# Latency benchmark
# ---------------------------------------------------------------------------


class TestConfluenceConnectorBenchmark:
    """pytest-benchmark: mean fetch() latency must be < 2 s with mocked responses."""

    @pytest.fixture
    def make_connector(self, mock_vault_cloud: None) -> ConfluenceConnector:
        return ConfluenceConnector(config=CLOUD_CONFIG)

    @respx.mock
    def test_fetch_under_2_seconds(
        self,
        benchmark: Any,  # noqa: ANN401
        make_connector: ConfluenceConnector,
        mock_vault_cloud: None,
    ) -> None:
        respx.get("https://acme.atlassian.net/wiki/rest/api/content/search").mock(
            return_value=httpx.Response(
                200, json={**MOCK_SEARCH_RESPONSE, "size": 50}
            )
        )

        async def run() -> list[Any]:
            await make_connector.authenticate()
            return await make_connector.fetch(ConnectorQuery(query="*", max_results=50))

        benchmark(lambda: asyncio.run(run()))
        assert benchmark.stats["mean"] < 2.0
