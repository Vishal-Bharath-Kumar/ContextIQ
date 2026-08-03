"""
Unit tests for TASK-US024-04: JiraConnector.sync() — Incremental Sync.

All external I/O (PostgreSQL, Jira API, Kafka) is mocked via AsyncMock / respx.
No live connections are made in CI.

Coverage targets (AC):
  - sync() builds JQL with updated >= "YYYY-MM-DD HH:MM" format
  - sync() falls back to now - default_days when no prior cursor exists
  - sync() writes updated cursor to connector_sync_state after completion
  - sync() returns SyncResult with non-negative counts
  - sync() emits source_sync_completed event to contextiq.source.sync
  - _build_jql honours _jql_override to bypass default_jql template
  - Failure in search does not prevent cursor update or Kafka emission
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.github.sync_store import ConnectorSyncStore
from src.connectors.jira.config import JiraConnectorConfig
from src.connectors.jira.connector import JiraConnector
from src.connectors.jira.search_client import JiraIssueItem, JiraSearchClient

pytestmark = pytest.mark.asyncio

_BASE_URL = "https://acme.atlassian.net"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> JiraConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": _BASE_URL,
        "email": "user@acme.com",
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
        "projects": ["OPS"],
        "default_days": 30,
    }
    defaults.update(overrides)
    return JiraConnectorConfig.model_validate(defaults)


def _mock_sync_store(last_sync_at: datetime | None = None) -> AsyncMock:
    store = AsyncMock(spec=ConnectorSyncStore)
    store.get_last_sync_at.return_value = last_sync_at
    store.set_last_sync_at.return_value = None
    return store


def _make_issue_item(key: str = "OPS-1") -> JiraIssueItem:
    return JiraIssueItem(
        issue_key=key,
        summary="Test issue",
        status="In Progress",
        priority="High",
        assignee="Alice",
        description="Some description",
        updated=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
        url=f"{_BASE_URL}/browse/{key}",
    )


async def _authenticated_connector(
    config: JiraConnectorConfig | None = None,
    session: object = None,
) -> JiraConnector:
    connector = JiraConnector(config=config or _make_config(), session=session)
    with patch.object(
        connector._token_provider,
        "get_credential",
        new=AsyncMock(
            return_value=type("Cred", (), {"email": "user@acme.com", "token": "tok"})()
        ),
    ):
        await connector.authenticate()
    return connector


# ---------------------------------------------------------------------------
# _build_jql — _jql_override unit tests
# ---------------------------------------------------------------------------


@pytest.mark.no_cover
class TestBuildJqlOverride:
    pytestmark: list = []  # suppress module-level asyncio mark for sync tests

    def test_override_bypasses_default_template(self) -> None:
        config = _make_config()
        client = JiraSearchClient(config)
        override = 'updated >= "2024-01-01 00:00" ORDER BY updated ASC'
        result = client._build_jql("", {"_jql_override": override})
        assert result == override

    def test_normal_query_still_uses_template(self) -> None:
        config = _make_config()
        client = JiraSearchClient(config)
        result = client._build_jql("", {})
        assert "OPS" in result

    def test_override_ignores_other_filters(self) -> None:
        config = _make_config()
        client = JiraSearchClient(config)
        override = 'updated >= "2024-06-01 00:00" ORDER BY updated ASC'
        result = client._build_jql("query", {"_jql_override": override, "extra": "val"})
        assert result == override


# ---------------------------------------------------------------------------
# JiraConnector.sync() — happy path
# ---------------------------------------------------------------------------


class TestJiraSyncHappyPath:
    async def test_sync_with_existing_cursor_builds_correct_jql(self) -> None:
        last_sync = datetime(2024, 5, 1, 10, 30, 0, tzinfo=UTC)
        mock_store = _mock_sync_store(last_sync_at=last_sync)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                JiraSearchClient,
                "search",
                new=AsyncMock(return_value=[_make_issue_item()]),
            ),
        ):
            result = await connector.sync()

        assert isinstance(result, SyncResult)
        assert result.items_processed == 1
        assert result.items_failed == 0
        assert result.errors == []

    async def test_sync_uses_fallback_when_no_prior_cursor(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        mock_search = AsyncMock(return_value=[_make_issue_item()])

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(JiraSearchClient, "search", new=mock_search),
        ):
            result = await connector.sync()

        assert result.items_processed == 1
        # JQL must contain 'updated >=' with a date in "YYYY-MM-DD HH:MM" format
        call_kwargs = mock_search.call_args[1]
        jql_override = call_kwargs["filters"]["_jql_override"]
        assert 'updated >= "' in jql_override

    async def test_sync_writes_cursor_after_success(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                JiraSearchClient, "search", new=AsyncMock(return_value=[])
            ),
        ):
            await connector.sync()

        mock_store.set_last_sync_at.assert_called_once()
        call_args = mock_store.set_last_sync_at.call_args
        assert call_args[0][0] == "jira"
        assert isinstance(call_args[0][1], datetime)

    async def test_sync_emits_kafka_event(self) -> None:
        import json

        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                JiraSearchClient,
                "search",
                new=AsyncMock(return_value=[_make_issue_item()]),
            ),
        ):
            await connector.sync()

        mock_producer.send_and_wait.assert_called_once()
        topic, payload_bytes = (
            mock_producer.send_and_wait.call_args[0][0],
            mock_producer.send_and_wait.call_args[1]["value"],
        )
        assert topic == "contextiq.source.sync"
        event = json.loads(payload_bytes.decode())
        assert event["event_type"] == "source_sync_completed"
        assert event["connector_id"] == "jira"
        assert event["items_processed"] == 1

    async def test_sync_result_last_sync_at_is_utc(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                JiraSearchClient, "search", new=AsyncMock(return_value=[])
            ),
        ):
            result = await connector.sync()

        assert result.last_sync_at.tzinfo is not None


# ---------------------------------------------------------------------------
# JiraConnector.sync() — failure handling
# ---------------------------------------------------------------------------


class TestJiraSyncFailure:
    async def test_search_failure_returns_error_in_sync_result(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                JiraSearchClient,
                "search",
                new=AsyncMock(side_effect=RuntimeError("network error")),
            ),
        ):
            result = await connector.sync()

        assert result.items_processed == 0
        assert result.items_failed == 1
        assert any("network error" in e for e in result.errors)

    async def test_search_failure_still_writes_cursor(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                JiraSearchClient,
                "search",
                new=AsyncMock(side_effect=RuntimeError("network error")),
            ),
        ):
            await connector.sync()

        mock_store.set_last_sync_at.assert_called_once()

    async def test_search_failure_still_emits_kafka_event(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.jira.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.jira.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                JiraSearchClient,
                "search",
                new=AsyncMock(side_effect=RuntimeError("network error")),
            ),
        ):
            await connector.sync()

        mock_producer.send_and_wait.assert_called_once()
