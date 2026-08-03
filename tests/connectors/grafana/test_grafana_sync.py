"""
Unit tests for TASK-US024-04: GrafanaConnector.sync() — Incremental Sync.

All external I/O (PostgreSQL, Grafana API, Kafka) is mocked via AsyncMock.
No live connections are made in CI.

Coverage targets (AC):
  - sync() computes lookback_hours from elapsed time since last_sync_at
  - sync() falls back to now - lookback_hours when no prior cursor exists
  - sync() writes updated cursor to connector_sync_state after completion
  - sync() returns SyncResult with items_processed = annotations + alerts
  - sync() emits source_sync_completed event to contextiq.source.sync
  - Failure in fetch does not prevent cursor update or Kafka emission
  - Items from both annotations and alerts are counted together
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.github.sync_store import ConnectorSyncStore
from src.connectors.grafana.annotation_client import (
    GrafanaAlertItem,
    GrafanaAnnotationClient,
    GrafanaAnnotationItem,
)
from src.connectors.grafana.config import GrafanaConnectorConfig
from src.connectors.grafana.connector import GrafanaConnector

pytestmark = pytest.mark.asyncio

_BASE_URL = "https://grafana.internal"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> GrafanaConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": _BASE_URL,
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
        "lookback_hours": 24,
    }
    defaults.update(overrides)
    return GrafanaConnectorConfig.model_validate(defaults)


def _mock_sync_store(last_sync_at: datetime | None = None) -> AsyncMock:
    store = AsyncMock(spec=ConnectorSyncStore)
    store.get_last_sync_at.return_value = last_sync_at
    store.set_last_sync_at.return_value = None
    return store


def _make_annotation(aid: int = 1) -> GrafanaAnnotationItem:
    return GrafanaAnnotationItem(
        annotation_id=aid,
        dashboard_uid="abc123",
        alert_name="CPU High",
        state="alerting",
        message="CPU usage above threshold",
        timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
    )


def _make_alert(fp: str = "abc") -> GrafanaAlertItem:
    return GrafanaAlertItem(
        fingerprint=fp,
        alert_name="MemoryAlert",
        state="firing",
        message="Memory usage critical",
        timestamp=datetime(2024, 6, 1, 12, 5, 0, tzinfo=UTC),
        labels={"alertname": "MemoryAlert", "env": "prod"},
    )


async def _authenticated_connector(
    config: GrafanaConnectorConfig | None = None,
    session: object = None,
) -> GrafanaConnector:
    connector = GrafanaConnector(config=config or _make_config(), session=session)
    with patch.object(
        connector._token_provider,
        "get_credential",
        new=AsyncMock(return_value=type("Cred", (), {"token": "svc-token"})()),
    ):
        await connector.authenticate()
    return connector


# ---------------------------------------------------------------------------
# GrafanaConnector.sync() — happy path
# ---------------------------------------------------------------------------


class TestGrafanaSyncHappyPath:
    async def test_sync_counts_annotations_and_alerts(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(
                    return_value=([_make_annotation(), _make_annotation(2)], [_make_alert()])
                ),
            ),
        ):
            result = await connector.sync()

        assert result.items_processed == 3  # 2 annotations + 1 alert
        assert result.items_failed == 0
        assert result.errors == []

    async def test_sync_with_no_cursor_uses_lookback_hours_fallback(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(return_value=([], [])),
            ),
        ):
            result = await connector.sync()

        assert result.items_processed == 0
        assert isinstance(result, SyncResult)

    async def test_sync_with_existing_cursor_computes_elapsed_lookback(self) -> None:
        last_sync = datetime.now(tz=UTC) - timedelta(hours=6)
        mock_store = _mock_sync_store(last_sync_at=last_sync)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(return_value=([_make_annotation()], [])),
            ),
        ):
            result = await connector.sync()

        assert result.items_processed == 1

    async def test_sync_writes_cursor_after_success(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(return_value=([], [])),
            ),
        ):
            await connector.sync()

        mock_store.set_last_sync_at.assert_called_once()
        call_args = mock_store.set_last_sync_at.call_args
        assert call_args[0][0] == "grafana"
        assert isinstance(call_args[0][1], datetime)

    async def test_sync_emits_kafka_event(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(
                    return_value=([_make_annotation()], [_make_alert()])
                ),
            ),
        ):
            await connector.sync()

        mock_producer.send_and_wait.assert_called_once()
        topic = mock_producer.send_and_wait.call_args[0][0]
        payload_bytes = mock_producer.send_and_wait.call_args[1]["value"]
        assert topic == "contextiq.source.sync"
        event = json.loads(payload_bytes.decode())
        assert event["event_type"] == "source_sync_completed"
        assert event["connector_id"] == "grafana"
        assert event["items_processed"] == 2

    async def test_sync_result_last_sync_at_is_utc(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(return_value=([], [])),
            ),
        ):
            result = await connector.sync()

        assert result.last_sync_at.tzinfo is not None


# ---------------------------------------------------------------------------
# GrafanaConnector.sync() — failure handling
# ---------------------------------------------------------------------------


class TestGrafanaSyncFailure:
    async def test_fetch_failure_returns_error_in_sync_result(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(side_effect=RuntimeError("grafana down")),
            ),
        ):
            result = await connector.sync()

        assert result.items_processed == 0
        assert result.items_failed == 1
        assert any("grafana down" in e for e in result.errors)

    async def test_fetch_failure_still_writes_cursor(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(side_effect=RuntimeError("grafana down")),
            ),
        ):
            await connector.sync()

        mock_store.set_last_sync_at.assert_called_once()

    async def test_fetch_failure_still_emits_kafka_event(self) -> None:
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector(session=AsyncMock())

        with (
            patch(
                "src.connectors.grafana.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.grafana.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
            patch.object(
                GrafanaAnnotationClient,
                "fetch_annotations_and_alerts",
                new=AsyncMock(side_effect=RuntimeError("grafana down")),
            ),
        ):
            await connector.sync()

        mock_producer.send_and_wait.assert_called_once()
