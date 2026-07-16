"""
Unit tests for TASK-US023-04: ConfluenceConnector.sync().

All external I/O is mocked — no live Confluence, Vault, PostgreSQL, or Kafka.

Coverage targets:
  - sync() uses 'lastModified >= "YYYY-MM-DD"' in the CQL extra clause
  - sync() defaults to now - default_days when no prior cursor exists
  - sync() uses stored last_sync_at when a cursor exists
  - sync() writes an updated cursor to ConnectorSyncStore after completion
  - sync() returns SyncResult with items_processed == total chunk count
  - sync() increments items_failed and records errors on per-page exceptions
  - sync() returns SyncResult with items_failed=1 when CQL search raises
  - sync() emits a source_sync_completed event to contextiq.source.sync
  - sync() emits event with correct items_processed count
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.confluence.config import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connectors.confluence.connector import ConfluenceConnector
from src.connectors.confluence.cql_client import ConfluencePageItem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = UTC
_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=_UTC)
_LAST_MOD = datetime(2024, 5, 20, 8, 0, 0, tzinfo=_UTC)


def _make_config(**overrides: object) -> ConfluenceConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": "https://acme.atlassian.net",
        "deployment_type": "cloud",
        "email": "user@acme.com",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
        "spaces": ["ENG"],
        "default_days": 30,
    }
    defaults.update(overrides)
    return ConfluenceConnectorConfig.model_validate(defaults)


def _make_page_item(page_id: str = "p1", body: str = "Hello") -> ConfluencePageItem:
    return ConfluencePageItem.model_validate(
        {
            "page_id": page_id,
            "title": "Test Page",
            "space_key": "ENG",
            "url": f"https://acme.atlassian.net/wiki/spaces/ENG/pages/{page_id}",
            "body_excerpt": body,
            "author": "Alice",
            "last_modified": _LAST_MOD,
        }
    )


def _authenticated_connector(config: ConfluenceConnectorConfig | None = None) -> ConfluenceConnector:
    from src.connectors.confluence.auth import ConfluenceCredential

    connector = ConfluenceConnector(config=config or _make_config(), session=MagicMock())
    connector._credential = ConfluenceCredential(
        token="tok",
        email="user@acme.com",
        deployment_type=ConfluenceDeploymentType.CLOUD,
    )
    return connector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_producer() -> AsyncMock:
    producer = AsyncMock()
    producer.send_and_wait = AsyncMock()
    return producer


# ---------------------------------------------------------------------------
# CQL filter tests
# ---------------------------------------------------------------------------


class TestSyncCqlFilter:
    @pytest.mark.asyncio
    async def test_uses_last_modified_cql_filter(self, mock_producer: AsyncMock) -> None:
        connector = _authenticated_connector()
        stored_cursor = datetime(2024, 5, 15, 0, 0, 0, tzinfo=_UTC)

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=stored_cursor)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(return_value=[])

            await connector.sync()

            call_kwargs = cql_instance.search.call_args.kwargs
            assert call_kwargs["extra_cql"] == 'lastModified >= "2024-05-15"'

    @pytest.mark.asyncio
    async def test_defaults_to_now_minus_default_days_when_no_cursor(
        self, mock_producer: AsyncMock
    ) -> None:
        config = _make_config(default_days=30)
        connector = _authenticated_connector(config)

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            mock_dt.side_effect = None
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=None)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(return_value=[])

            await connector.sync()

            call_kwargs = cql_instance.search.call_args.kwargs
            # default_days=30 from _NOW → 2024-05-02
            expected_date = (_NOW - timedelta(days=30)).strftime("%Y-%m-%d")
            assert call_kwargs["extra_cql"] == f'lastModified >= "{expected_date}"'


# ---------------------------------------------------------------------------
# Cursor persistence tests
# ---------------------------------------------------------------------------


class TestSyncCursorPersistence:
    @pytest.mark.asyncio
    async def test_cursor_written_after_sync(self, mock_producer: AsyncMock) -> None:
        connector = _authenticated_connector()

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=None)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(return_value=[])

            await connector.sync()

            store_instance.set_last_sync_at.assert_awaited_once_with("confluence", _NOW)


# ---------------------------------------------------------------------------
# SyncResult tests
# ---------------------------------------------------------------------------


class TestSyncResult:
    @pytest.mark.asyncio
    async def test_items_processed_equals_total_chunk_count(
        self, mock_producer: AsyncMock
    ) -> None:
        connector = _authenticated_connector()
        pages = [_make_page_item("p1", "Short content"), _make_page_item("p2", "Other content")]

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=None)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(return_value=pages)

            result = await connector.sync()

        # Each short page → 1 chunk; 2 pages → 2 chunks
        assert result.items_processed == 2
        assert result.items_failed == 0
        assert result.errors == []
        assert result.last_sync_at == _NOW

    @pytest.mark.asyncio
    async def test_items_failed_incremented_on_per_page_error(
        self, mock_producer: AsyncMock
    ) -> None:
        connector = _authenticated_connector()
        pages = [_make_page_item("bad-page", "content")]

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.strip_confluence_storage",
                side_effect=ValueError("bad html"),
            ),
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=None)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(return_value=pages)

            result = await connector.sync()

        assert result.items_failed == 1
        assert any("bad-page" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_cql_search_failure_returns_failed_result(
        self, mock_producer: AsyncMock
    ) -> None:
        connector = _authenticated_connector()

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=None)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(side_effect=RuntimeError("network down"))

            result = await connector.sync()

        assert result.items_processed == 0
        assert result.items_failed == 1
        assert any("CQL sync search failed" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Kafka event tests
# ---------------------------------------------------------------------------


class TestSyncKafkaEvent:
    @pytest.mark.asyncio
    async def test_emits_source_sync_completed_event(self, mock_producer: AsyncMock) -> None:
        import json

        connector = _authenticated_connector()
        pages = [_make_page_item("p1", "Hello")]

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=None)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(return_value=pages)

            await connector.sync()

        mock_producer.send_and_wait.assert_awaited_once()
        topic, payload_kwarg = (
            mock_producer.send_and_wait.call_args.args[0],
            mock_producer.send_and_wait.call_args.kwargs["value"],
        )
        assert topic == "contextiq.source.sync"
        event = json.loads(payload_kwarg.decode())
        assert event["event_type"] == "source_sync_completed"
        assert event["connector_id"] == "confluence"
        assert event["items_processed"] == 1

    @pytest.mark.asyncio
    async def test_event_not_emitted_on_cql_failure(self, mock_producer: AsyncMock) -> None:
        connector = _authenticated_connector()

        with (
            patch("src.connectors.confluence.connector.datetime") as mock_dt,
            patch(
                "src.connectors.confluence.connector.ConnectorSyncStore"
            ) as MockStore,
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient"
            ) as MockCQL,
            patch(
                "src.connectors.confluence.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            mock_dt.now.return_value = _NOW
            store_instance = MockStore.return_value
            store_instance.get_last_sync_at = AsyncMock(return_value=None)
            store_instance.set_last_sync_at = AsyncMock()

            cql_instance = MockCQL.return_value
            cql_instance.search = AsyncMock(side_effect=RuntimeError("down"))

            await connector.sync()

        mock_producer.send_and_wait.assert_not_awaited()
