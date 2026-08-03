# TASK-US024-04 — `JiraConnector.sync()` and `GrafanaConnector.sync()`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US024-04 |
| User Story | US-024 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `sync()` on both `JiraConnector` and `GrafanaConnector`. Jira uses a JQL `updated >= {last_sync_at}` clause to fetch only changed issues; Grafana uses a `from` epoch-ms timestamp on the annotations endpoint to retrieve only new annotations since the last sync. Both persist their sync cursor via `ConnectorSyncStore` (reused from TASK-US022-04) and emit a DR-005 `StateTransitionEvent` on the `contextiq.source.sync` Kafka topic.

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]`, SQLAlchemy 2.x async, `aiokafka`

**File locations:**
- `src/connectors/jira/connector.py` — `JiraConnector.sync()` (extend existing class)
- `src/connectors/grafana/connector.py` — `GrafanaConnector.sync()` (extend existing class)
- `tests/connectors/jira/test_jira_sync.py`
- `tests/connectors/grafana/test_grafana_sync.py`

**`JiraConnector.sync()`:**

```python
# src/connectors/jira/connector.py  — extend existing class
from datetime import datetime, timezone, timedelta
from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.jira.search_client import JiraSearchClient
from src.connectors.github.sync_store  import ConnectorSyncStore   # reused

    async def sync(self) -> SyncResult:
        sync_store = ConnectorSyncStore(self._session)
        now        = datetime.now(tz=timezone.utc)

        last_sync  = await sync_store.get_last_sync_at("jira")
        if last_sync is None:
            last_sync = now - timedelta(days=self._config.default_days)

        # JQL date format: "YYYY-MM-DD HH:mm"  (Jira does not accept ISO-8601 with 'T' in JQL)
        since_str  = last_sync.strftime("%Y-%m-%d %H:%M")
        sync_jql   = f'updated >= "{since_str}" ORDER BY updated ASC'

        items_processed = 0
        items_failed    = 0
        errors: list[str] = []

        try:
            client = JiraSearchClient(self._config)
            # Temporarily override default_jql to use sync-specific JQL
            import dataclasses
            issues = await client.search(
                query        = "",
                auth_headers = self._auth_headers(),
                filters      = {"_jql_override": sync_jql},
                max_results  = 500,
            )
            items_processed = len(issues)
        except Exception as exc:
            items_failed = 1
            errors.append(f"Jira sync search failed: {type(exc).__name__}: {exc}")

        await sync_store.set_last_sync_at("jira", now)
        await self._emit_sync_event(items_processed=items_processed, synced_at=now)

        return SyncResult(
            items_processed = items_processed,
            items_failed    = items_failed,
            last_sync_at    = now,
            errors          = errors,
        )

    async def _emit_sync_event(self, items_processed: int, synced_at: datetime) -> None:
        import json
        from src.events.producer import get_kafka_producer
        event = {"event_type": "source_sync_completed", "connector_id": "jira",
                 "items_processed": items_processed, "synced_at": synced_at.isoformat()}
        producer = await get_kafka_producer()
        await producer.send_and_wait("contextiq.source.sync", value=json.dumps(event).encode())
```

**`JiraSearchClient._build_jql` extension — `_jql_override` filter:**

```python
# src/connectors/jira/search_client.py  — extend _build_jql
def _build_jql(self, query: str, filters: dict[str, str]) -> str:
    if "_jql_override" in filters:
        return filters["_jql_override"]   # sync path bypasses default_jql template
    ...  # existing logic unchanged
```

**`GrafanaConnector.sync()`:**

```python
# src/connectors/grafana/connector.py  — extend existing class
from datetime import datetime, timezone, timedelta
from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.grafana.annotation_client import GrafanaAnnotationClient
from src.connectors.github.sync_store         import ConnectorSyncStore

    async def sync(self) -> SyncResult:
        sync_store  = ConnectorSyncStore(self._session)
        now         = datetime.now(tz=timezone.utc)

        last_sync   = await sync_store.get_last_sync_at("grafana")
        if last_sync is None:
            last_sync = now - timedelta(hours=self._config.lookback_hours)

        items_processed = 0
        items_failed    = 0
        errors: list[str] = []

        try:
            # Temporarily use last_sync as lookback window for this sync run
            original_lookback  = self._config.lookback_hours
            elapsed_hours      = (now - last_sync).total_seconds() / 3600
            # GrafanaAnnotationClient reads lookback_hours from config; override via model_copy
            sync_config = self._config.model_copy(
                update={"lookback_hours": max(1, int(elapsed_hours) + 1)}
            )
            client = GrafanaAnnotationClient(sync_config)
            annotations, alerts = await client.fetch_annotations_and_alerts(
                auth_headers = self._auth_headers(),
                max_results  = 500,
            )
            items_processed = len(annotations) + len(alerts)
        except Exception as exc:
            items_failed = 1
            errors.append(f"Grafana sync failed: {type(exc).__name__}: {exc}")

        await sync_store.set_last_sync_at("grafana", now)
        await self._emit_sync_event(items_processed=items_processed, synced_at=now)

        return SyncResult(
            items_processed = items_processed,
            items_failed    = items_failed,
            last_sync_at    = now,
            errors          = errors,
        )

    async def _emit_sync_event(self, items_processed: int, synced_at: datetime) -> None:
        import json
        from src.events.producer import get_kafka_producer
        event = {"event_type": "source_sync_completed", "connector_id": "grafana",
                 "items_processed": items_processed, "synced_at": synced_at.isoformat()}
        producer = await get_kafka_producer()
        await producer.send_and_wait("contextiq.source.sync", value=json.dumps(event).encode())
```

**`GrafanaConnectorConfig.model_copy()` pattern:**

`GrafanaConnectorConfig` is a `BaseSettings` (Pydantic v2). `model_copy(update={...})` produces a new immutable config instance with the overridden `lookback_hours`, satisfying the frozen-model convention without mutating the module-level config object.

**`ConnectorSyncStore` reuse:**

`ConnectorSyncStore` from TASK-US022-04 is used directly with connector IDs `"jira"` and `"grafana"`. The `connector_sync_state` table schema is connector-agnostic (`connector_id VARCHAR PK, last_sync_at TIMESTAMPTZ`). No Alembic migration change is needed.

## Acceptance Criteria

- [ ] `JiraConnector.sync()` builds JQL with `updated >= "{last_sync_date_time}"` format
- [ ] `JiraConnector.sync()` falls back to `now - default_days` when no prior cursor exists
- [ ] `GrafanaConnector.sync()` computes `lookback_hours` from elapsed time since `last_sync_at`
- [ ] Both `sync()` methods write the updated cursor to `connector_sync_state` after completion
- [ ] Both `sync()` methods return `SyncResult` with non-negative counts
- [ ] Both emit `source_sync_completed` event to `contextiq.source.sync` Kafka topic
- [ ] Single-connector failure (Jira or Grafana) does not affect the other connector's sync

## Dependencies

- TASK-US024-01 (`_auth_headers()`, configs)
- TASK-US024-02 (`JiraSearchClient`)
- TASK-US024-03 (`GrafanaAnnotationClient`)
- TASK-US021-01 (`SyncResult`)
- TASK-US022-04 (`ConnectorSyncStore` — reused directly)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `ConnectorSyncStore`, HTTP clients, and Kafka producer via `AsyncMock`
- [ ] `mypy --strict` passes; no `ruff` lint errors
