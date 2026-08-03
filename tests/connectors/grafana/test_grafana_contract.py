"""
Contract test suite for TASK-US024-05:
  - TestGrafanaConnector — 6 BaseConnectorTestCase contracts + targeted overrides
  - test_grafana_disabled_raises_auth_error — AC-5 independent enable/disable
  - test_grafana_fetch_degrades_on_alertmanager_failure — partial result on 404
  - test_grafana_fetch_under_3_seconds — AC-6 latency benchmark (mocked)

All HTTP calls are intercepted by respx; no live Grafana or Vault in CI.
"""
from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult
from src.connector_sdk.schemas.sync import SyncResult
from src.connector_sdk.testing import BaseConnectorTestCase
from src.connectors.grafana.auth import GrafanaCredential
from src.connectors.grafana.config import GrafanaConnectorConfig
from src.connectors.grafana.connector import GrafanaConnector

# ---------------------------------------------------------------------------
# Constants / shared fixtures
# ---------------------------------------------------------------------------

GRAFANA_CONFIG = GrafanaConnectorConfig(
    enabled=True,
    base_url="https://grafana.internal",
    lookback_hours=24,
    vault_role_id="test-role",
    vault_secret_id="test-secret",
)
MOCK_GRAFANA_CREDENTIAL = GrafanaCredential(token="glsa_test_service_token")

MOCK_ANNOTATIONS = [
    {
        "id": 1,
        "text": "Deploy spike",
        "newState": "alerting",
        "time": 1720000000000,
        "dashboardUID": "abc",
    }
]
MOCK_ALERTS = [
    {
        "fingerprint": "f1",
        "labels": {"alertname": "HighCPU"},
        "status": {"state": "firing"},
        "annotations": {"message": "CPU > 90%"},
        "startsAt": "2026-07-09T07:00:00Z",
    }
]

_VAULT_TARGET = "src.connectors.grafana.connector.GrafanaTokenProvider.get_credential"
_ANNOTATIONS_URL = "https://grafana.internal/api/annotations"
_ALERTS_URL = "https://grafana.internal/api/alertmanager/grafana/api/v2/alerts"
_HEALTH_URL = "https://grafana.internal/api/health"


@pytest.fixture
def mock_grafana_vault() -> Generator[None, None, None]:
    with patch(
        _VAULT_TARGET,
        new_callable=AsyncMock,
        return_value=MOCK_GRAFANA_CREDENTIAL,
    ):
        yield


# ---------------------------------------------------------------------------
# Contract test class — all 6 SDK tests
# ---------------------------------------------------------------------------


class TestGrafanaConnector(BaseConnectorTestCase):
    """6 SDK contract tests for GrafanaConnector."""

    @pytest.fixture
    def make_connector(self, mock_grafana_vault: None) -> GrafanaConnector:
        return GrafanaConnector(config=GRAFANA_CONFIG)

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        return ConnectorQuery(query="CPU", max_results=10)

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(  # type: ignore[override]
        self,
        make_connector: GrafanaConnector,
        sample_query: ConnectorQuery,
        mock_grafana_vault: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get(_ANNOTATIONS_URL).mock(
            return_value=httpx.Response(200, json=MOCK_ANNOTATIONS)
        )
        respx.get(_ALERTS_URL).mock(
            return_value=httpx.Response(200, json=MOCK_ALERTS)
        )
        results = await make_connector.fetch(sample_query)
        assert results
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, ConnectorResult)
            assert isinstance(r.fetched_at, datetime)
            assert r.source_id
            assert isinstance(r.content, str)
        assert any(r.source_id == "grafana:annotation:1" for r in results)
        assert any(r.source_id == "grafana:alert:f1" for r in results)

    @respx.mock
    async def test_fetch_respects_max_results(  # type: ignore[override]
        self,
        make_connector: GrafanaConnector,
        sample_query: ConnectorQuery,
    ) -> None:
        await make_connector.authenticate()
        respx.get(_ANNOTATIONS_URL).mock(
            return_value=httpx.Response(200, json=MOCK_ANNOTATIONS)
        )
        respx.get(_ALERTS_URL).mock(
            return_value=httpx.Response(200, json=MOCK_ALERTS)
        )
        results = await make_connector.fetch(sample_query)
        assert len(results) <= sample_query.max_results

    @respx.mock
    async def test_sync_returns_sync_result(  # type: ignore[override]
        self,
        make_connector: GrafanaConnector,
    ) -> None:
        await make_connector.authenticate()
        respx.get(_ANNOTATIONS_URL).mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(_ALERTS_URL).mock(
            return_value=httpx.Response(200, json=[])
        )
        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore.get_last_sync_at",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore.set_last_sync_at",
                new_callable=AsyncMock,
            ),
            patch(
                "src.connectors.grafana.connector.GrafanaConnector._emit_sync_event",
                new_callable=AsyncMock,
            ),
        ):
            result = await make_connector.sync()
            assert isinstance(result, SyncResult)
            assert result.items_processed >= 0
            assert result.items_failed >= 0
            assert isinstance(result.last_sync_at, datetime)

    @respx.mock
    async def test_health_check_returns_health_status(  # type: ignore[override]
        self,
        make_connector: GrafanaConnector,
        mock_grafana_vault: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get(_HEALTH_URL).mock(
            return_value=httpx.Response(200, json={"database": "ok"})
        )
        status = await make_connector.health_check()
        assert isinstance(status, HealthStatus)
        assert isinstance(status.healthy, bool)
        assert isinstance(status.message, str)
        assert len(status.message) <= 200
        assert isinstance(status.checked_at, datetime)

    @respx.mock
    async def test_health_check_does_not_raise_on_repeated_calls(  # type: ignore[override]
        self,
        make_connector: GrafanaConnector,
        mock_grafana_vault: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get(_HEALTH_URL).mock(
            return_value=httpx.Response(200, json={"database": "ok"})
        )
        for _ in range(3):
            status = await make_connector.health_check()
            assert isinstance(status, HealthStatus)


# ---------------------------------------------------------------------------
# AC-5: independent enable/disable
# ---------------------------------------------------------------------------


async def test_grafana_disabled_raises_auth_error(mock_grafana_vault: None) -> None:
    """Disabling Grafana raises ConnectorAuthError; does not affect Jira."""
    disabled = GRAFANA_CONFIG.model_copy(update={"enabled": False})
    connector = GrafanaConnector(config=disabled)
    with pytest.raises(ConnectorAuthError, match="disabled"):
        await connector.authenticate()


# ---------------------------------------------------------------------------
# Alert degradation: Alertmanager 404 → annotations still returned
# ---------------------------------------------------------------------------


@respx.mock
async def test_grafana_fetch_degrades_on_alertmanager_failure(
    mock_grafana_vault: None,
) -> None:
    """404 from Alertmanager must not raise; annotations are still returned."""
    connector = GrafanaConnector(config=GRAFANA_CONFIG)
    await connector.authenticate()
    respx.get(_ANNOTATIONS_URL).mock(
        return_value=httpx.Response(200, json=MOCK_ANNOTATIONS)
    )
    respx.get(_ALERTS_URL).mock(return_value=httpx.Response(404))
    results = await connector.fetch(ConnectorQuery(query="grafana", max_results=50))
    assert any(r.source_id == "grafana:annotation:1" for r in results)
    # No alert results — but no exception raised
    assert all(r.metadata.extra["type"] == "annotation" for r in results)


# ---------------------------------------------------------------------------
# AC-6: latency benchmark — fetch() must complete in < 3 s (mocked)
# ---------------------------------------------------------------------------


@respx.mock
def test_grafana_fetch_under_3_seconds(benchmark: object, mock_grafana_vault: None) -> None:
    """Verify fetch() mean latency < 3 s for ≤ 50 results (mocked responses)."""
    respx.get(_ANNOTATIONS_URL).mock(
        return_value=httpx.Response(200, json=MOCK_ANNOTATIONS)
    )
    respx.get(_ALERTS_URL).mock(
        return_value=httpx.Response(200, json=MOCK_ALERTS)
    )

    async def run() -> list[ConnectorResult]:
        connector = GrafanaConnector(config=GRAFANA_CONFIG)
        await connector.authenticate()
        return await connector.fetch(ConnectorQuery(query="CPU", max_results=50))

    benchmark(lambda: asyncio.run(run()))  # type: ignore[attr-defined]
    assert benchmark.stats["mean"] < 3.0  # type: ignore[attr-defined]
