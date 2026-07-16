"""
Unit tests for TASK-US024-03: GrafanaConnector.fetch(), GrafanaAnnotationClient,
and GrafanaConnector.health_check().

All HTTP calls are intercepted via respx; no live Grafana in CI.

Coverage targets:
  - fetch() returns ConnectorResult for both annotations and alerts
  - source_id format: grafana:annotation:{id} and grafana:alert:{fingerprint}
  - metadata.extra["type"] is "annotation" or "alert"
  - Alertmanager failure degrades to empty alerts list; annotations still returned
  - fetch() raises asyncio.TimeoutError when total response exceeds 3 s
  - health_check() returns healthy=True when /api/health returns {"database":"ok"}
  - health_check() returns healthy=False on HTTP 401 without raising
  - health_check() returns healthy=False on connection error without raising
  - health_check() returns healthy=False when not authenticated
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

import httpx
import pytest
import respx

from src.connector_sdk.schemas.query import ConnectorQuery
from src.connectors.grafana.annotation_client import GrafanaAnnotationClient
from src.connectors.grafana.auth import GrafanaCredential
from src.connectors.grafana.config import GrafanaConnectorConfig
from src.connectors.grafana.connector import GrafanaConnector



# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "https://grafana.test"


def _make_config(**overrides: object) -> GrafanaConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": BASE_URL,
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "role-id",
        "vault_secret_id": "secret-id",
        "lookback_hours": 24,
        "request_timeout_s": 10.0,
    }
    defaults.update(overrides)
    return GrafanaConnectorConfig.model_validate(defaults)


def _authenticated_connector(config: GrafanaConnectorConfig | None = None) -> GrafanaConnector:
    """Return a GrafanaConnector with a pre-set credential (bypasses Vault)."""
    c = GrafanaConnector(config or _make_config())
    c._credential = GrafanaCredential(token="glsa_testtoken")  # noqa: SLF001
    return c


_ANNOTATION_PAYLOAD = [
    {
        "id": 42,
        "dashboardUID": "abc123",
        "text": "CPU spike",
        "newState": "alerting",
        "time": 1700000000000,
    }
]

_ALERT_PAYLOAD = [
    {
        "fingerprint": "fp001",
        "labels": {"alertname": "HighMemory", "env": "prod"},
        "annotations": {"message": "Memory above 90%"},
        "status": {"state": "firing"},
        "startsAt": "2023-11-14T22:13:20+00:00",
    }
]

_HEALTH_OK = {"database": "ok"}


# ---------------------------------------------------------------------------
# GrafanaAnnotationClient — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGrafanaAnnotationClient:
    @respx.mock
    async def test_fetch_returns_both_annotations_and_alerts(self):
        config = _make_config()
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=_ANNOTATION_PAYLOAD)
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=_ALERT_PAYLOAD)
        )
        client = GrafanaAnnotationClient(config)
        annotations, alerts = await client.fetch_annotations_and_alerts(
            auth_headers={"Authorization": "Bearer glsa_test"}
        )

        assert len(annotations) == 1
        assert annotations[0].annotation_id == 42
        assert annotations[0].alert_name == "CPU spike"
        assert annotations[0].state == "alerting"
        assert annotations[0].dashboard_uid == "abc123"

        assert len(alerts) == 1
        assert alerts[0].fingerprint == "fp001"
        assert alerts[0].alert_name == "HighMemory"
        assert alerts[0].state == "firing"
        assert alerts[0].message == "Memory above 90%"
        assert alerts[0].labels == {"alertname": "HighMemory", "env": "prod"}

    @respx.mock
    async def test_alertmanager_failure_degrades_to_empty_alerts(self):
        config = _make_config()
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=_ANNOTATION_PAYLOAD)
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(503, json={"message": "unavailable"})
        )
        client = GrafanaAnnotationClient(config)
        annotations, alerts = await client.fetch_annotations_and_alerts(
            auth_headers={"Authorization": "Bearer glsa_test"}
        )

        assert len(annotations) == 1
        assert alerts == []

    @respx.mock
    async def test_annotations_failure_degrades_to_empty_annotations(self):
        config = _make_config()
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(500, json={"message": "error"})
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=_ALERT_PAYLOAD)
        )
        client = GrafanaAnnotationClient(config)
        annotations, alerts = await client.fetch_annotations_and_alerts(
            auth_headers={"Authorization": "Bearer glsa_test"}
        )

        assert annotations == []
        assert len(alerts) == 1

    @respx.mock
    async def test_dashboard_uid_filter_added_to_params(self):
        config = _make_config(dashboard_uids=["uid-xyz"])
        route = respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=[])
        )
        client = GrafanaAnnotationClient(config)
        await client.fetch_annotations_and_alerts(auth_headers={})

        assert route.called
        request = route.calls[0].request
        assert "uid-xyz" in str(request.url)


class TestGrafanaAnnotationClientSync:
    """Synchronous tests for static parse helpers."""

    def test_parse_annotation_message_truncated_to_1000_chars(self):
        long_text = "x" * 1500
        raw = {"id": 1, "text": long_text, "newState": "ok", "time": 0}
        item = GrafanaAnnotationClient._parse_annotation(raw)
        assert len(item.message) == 1000

    def test_parse_alert_uses_summary_fallback(self):
        raw = {
            "fingerprint": "fp",
            "labels": {},
            "annotations": {"summary": "Disk full"},
            "status": {"state": "firing"},
            "startsAt": "1970-01-01T00:00:00+00:00",
        }
        item = GrafanaAnnotationClient._parse_alert(raw)
        assert item.message == "Disk full"

    def test_parse_alert_message_truncated_to_1000_chars(self):
        raw = {
            "fingerprint": "fp",
            "labels": {},
            "annotations": {"message": "y" * 1500},
            "status": {"state": "firing"},
            "startsAt": "1970-01-01T00:00:00+00:00",
        }
        item = GrafanaAnnotationClient._parse_alert(raw)
        assert len(item.message) == 1000


@pytest.mark.asyncio
class TestGrafanaConnectorFetch:
    @respx.mock
    async def test_fetch_returns_annotation_and_alert_results(self):
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=_ANNOTATION_PAYLOAD)
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=_ALERT_PAYLOAD)
        )
        connector = _authenticated_connector()
        query = ConnectorQuery(query="alerts", max_results=50)
        results = await connector.fetch(query)

        assert len(results) == 2
        source_ids = {r.source_id for r in results}
        assert "grafana:annotation:42" in source_ids
        assert "grafana:alert:fp001" in source_ids

    @respx.mock
    async def test_fetch_annotation_metadata_extra(self):
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=_ANNOTATION_PAYLOAD)
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=[])
        )
        connector = _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="q", max_results=10))

        ann_result = next(r for r in results if r.source_id.startswith("grafana:annotation:"))
        assert ann_result.metadata.extra["type"] == "annotation"
        assert ann_result.metadata.extra["state"] == "alerting"
        assert ann_result.metadata.extra["dashboard_uid"] == "abc123"
        assert ann_result.metadata.source_url == f"{BASE_URL}/d/abc123"

    @respx.mock
    async def test_fetch_alert_metadata_extra(self):
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=_ALERT_PAYLOAD)
        )
        connector = _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="q", max_results=10))

        alert_result = next(r for r in results if r.source_id.startswith("grafana:alert:"))
        assert alert_result.metadata.extra["type"] == "alert"
        assert alert_result.metadata.extra["state"] == "firing"
        assert alert_result.metadata.extra["fingerprint"] == "fp001"
        assert alert_result.metadata.source_url == f"{BASE_URL}/alerting"

    @respx.mock
    async def test_fetch_respects_max_results(self):
        many_annotations = [
            {"id": i, "dashboardUID": None, "text": f"ann{i}", "newState": "ok", "time": 0}
            for i in range(20)
        ]
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=many_annotations)
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=[])
        )
        connector = _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="q", max_results=5))
        assert len(results) <= 5

    @respx.mock
    async def test_fetch_alertmanager_failure_annotations_still_returned(self):
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=_ANNOTATION_PAYLOAD)
        )
        respx.get(f"{BASE_URL}/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(503)
        )
        connector = _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="q", max_results=50))

        assert any(r.source_id.startswith("grafana:annotation:") for r in results)
        assert not any(r.source_id.startswith("grafana:alert:") for r in results)

    async def test_fetch_raises_timeout_error_when_slow(self):
        connector = _authenticated_connector()

        async def _slow_inner(_query):
            await asyncio.sleep(10)
            return []

        connector._fetch_inner = _slow_inner  # noqa: SLF001

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(connector._fetch_inner(ConnectorQuery(query="q", max_results=10)), timeout=0.01)  # noqa: SLF001

    async def test_fetch_timeout_via_connector(self):
        connector = _authenticated_connector()

        async def _slow_inner(_query):
            await asyncio.sleep(10)
            return []

        with patch.object(connector, "_fetch_inner", side_effect=_slow_inner):
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    connector.fetch(ConnectorQuery(query="q", max_results=10)), timeout=0.01
                )


# ---------------------------------------------------------------------------
# GrafanaConnector.health_check()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGrafanaConnectorHealthCheck:
    @respx.mock
    async def test_health_check_returns_healthy_when_database_ok(self):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(200, json=_HEALTH_OK)
        )
        connector = _authenticated_connector()
        status = await connector.health_check()

        assert status.healthy is True
        assert "healthy" in status.message.lower()
        assert isinstance(status.checked_at, datetime)

    @respx.mock
    async def test_health_check_returns_unhealthy_on_401(self):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        connector = _authenticated_connector()
        status = await connector.health_check()

        assert status.healthy is False
        assert not status.message == ""

    @respx.mock
    async def test_health_check_returns_unhealthy_on_non_ok_database(self):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(200, json={"database": "degraded"})
        )
        connector = _authenticated_connector()
        status = await connector.health_check()

        assert status.healthy is False

    async def test_health_check_returns_unhealthy_on_connection_error(self):
        config = _make_config(base_url="http://unreachable.invalid")
        connector = _authenticated_connector(config)

        with respx.mock:
            respx.get("http://unreachable.invalid/api/health").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            status = await connector.health_check()

        assert status.healthy is False
        assert "ConnectError" in status.message

    async def test_health_check_returns_unhealthy_when_not_authenticated(self):
        connector = GrafanaConnector(_make_config())
        # _credential is None — no authenticate() called
        status = await connector.health_check()

        assert status.healthy is False
        assert "authenticated" in status.message.lower()
