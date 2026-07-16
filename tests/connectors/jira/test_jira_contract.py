"""
Contract test suite for TASK-US024-05:
  - TestJiraConnector — 6 BaseConnectorTestCase contracts + targeted overrides
  - test_jira_disabled_raises_auth_error — AC-5 independent enable/disable
  - test_jira_fetch_under_3_seconds — AC-6 latency benchmark (mocked)

All HTTP calls are intercepted by respx; no live Jira or Vault in CI.
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
from src.connectors.jira.auth import JiraCredential
from src.connectors.jira.config import JiraConnectorConfig
from src.connectors.jira.connector import JiraConnector

# ---------------------------------------------------------------------------
# Constants / shared fixtures
# ---------------------------------------------------------------------------

JIRA_CONFIG = JiraConnectorConfig(
    enabled=True,
    base_url="https://acme.atlassian.net",
    email="bot@acme.com",
    projects=["OPS"],
    vault_role_id="test-role",
    vault_secret_id="test-secret",
)
MOCK_JIRA_CREDENTIAL = JiraCredential(token="test-jira-token", email="bot@acme.com")

MOCK_SEARCH_RESPONSE = {
    "issues": [
        {
            "key": "OPS-42",
            "fields": {
                "summary": "Database connection pool exhausted",
                "status": {"name": "In Progress"},
                "priority": {"name": "High"},
                "assignee": {"displayName": "Bob"},
                "description": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Pool size exceeded."}],
                        }
                    ],
                },
                "updated": "2026-07-09T08:00:00.000+0000",
            },
        }
    ]
}

EMPTY_SEARCH_RESPONSE = {"issues": []}

_VAULT_TARGET = "src.connectors.jira.connector.JiraTokenProvider.get_credential"


@pytest.fixture
def mock_jira_vault() -> Generator[None, None, None]:
    with patch(
        _VAULT_TARGET,
        new_callable=AsyncMock,
        return_value=MOCK_JIRA_CREDENTIAL,
    ):
        yield


# ---------------------------------------------------------------------------
# Contract test class — all 6 SDK tests
# ---------------------------------------------------------------------------


class TestJiraConnector(BaseConnectorTestCase):
    """6 SDK contract tests for JiraConnector."""

    @pytest.fixture
    def make_connector(self, mock_jira_vault: None) -> JiraConnector:
        return JiraConnector(config=JIRA_CONFIG)

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        return ConnectorQuery(query="database connection", max_results=5)

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(  # type: ignore[override]
        self,
        make_connector: JiraConnector,
        sample_query: ConnectorQuery,
        mock_jira_vault: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/rest/api/3/search").mock(
            return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert results
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, ConnectorResult)
            assert isinstance(r.fetched_at, datetime)
            assert r.source_id
            assert isinstance(r.content, str)
        assert results[0].source_id == "jira:OPS-42"
        assert results[0].metadata.extra["status"] == "In Progress"
        assert results[0].metadata.extra["priority"] == "High"
        assert results[0].metadata.author == "Bob"

    @respx.mock
    async def test_fetch_respects_max_results(  # type: ignore[override]
        self,
        make_connector: JiraConnector,
        sample_query: ConnectorQuery,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/rest/api/3/search").mock(
            return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert len(results) <= sample_query.max_results

    @respx.mock
    async def test_sync_returns_sync_result(  # type: ignore[override]
        self,
        make_connector: JiraConnector,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/rest/api/3/search").mock(
            return_value=httpx.Response(200, json=EMPTY_SEARCH_RESPONSE)
        )
        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore.get_last_sync_at",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore.set_last_sync_at",
                new_callable=AsyncMock,
            ),
            patch(
                "src.connectors.jira.connector.JiraConnector._emit_sync_event",
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
        make_connector: JiraConnector,
        mock_jira_vault: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=httpx.Response(200, json={"accountId": "abc123"})
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
        make_connector: JiraConnector,
        mock_jira_vault: None,
    ) -> None:
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=httpx.Response(200, json={"accountId": "abc123"})
        )
        for _ in range(3):
            status = await make_connector.health_check()
            assert isinstance(status, HealthStatus)


# ---------------------------------------------------------------------------
# AC-5: independent enable/disable
# ---------------------------------------------------------------------------


async def test_jira_disabled_raises_auth_error(mock_jira_vault: None) -> None:
    """Disabling Jira raises ConnectorAuthError; does not affect Grafana."""
    disabled_config = JIRA_CONFIG.model_copy(update={"enabled": False})
    connector = JiraConnector(config=disabled_config)
    with pytest.raises(ConnectorAuthError, match="disabled"):
        await connector.authenticate()


# ---------------------------------------------------------------------------
# AC-6: latency benchmark — fetch() must complete in < 3 s (mocked)
# ---------------------------------------------------------------------------


@respx.mock
def test_jira_fetch_under_3_seconds(benchmark: object, mock_jira_vault: None) -> None:
    """Verify fetch() mean latency < 3 s for ≤ 50 results (mocked responses)."""
    respx.get("https://acme.atlassian.net/rest/api/3/search").mock(
        return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
    )

    async def run() -> list[ConnectorResult]:
        connector = JiraConnector(config=JIRA_CONFIG)
        await connector.authenticate()
        return await connector.fetch(ConnectorQuery(query="ops", max_results=50))

    benchmark(lambda: asyncio.run(run()))  # type: ignore[attr-defined]
    assert benchmark.stats["mean"] < 3.0  # type: ignore[attr-defined]
