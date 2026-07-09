# TASK-US007-04 — Connector Registry: Active Connector Selection from Execution Plan

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US007-04 |
| User Story | US-007 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement the `ConnectorRegistry` that maps source IDs from the `execution_plan` to live `BaseConnector` instances, filters out inactive connectors, and provides health-aware dispatch. The registry is the bridge between the static connector configuration (PostgreSQL) and the dynamic runtime dispatch in `ParallelConnectorDispatcher`.

## Implementation Details

**Technology:** Python 3.11+, dependency injection, `asyncio`

**File locations:**
- `src/agents/retrieval/connector_registry.py` — `ConnectorRegistry` class
- `src/agents/retrieval/connector_loader.py` — loads connectors from DB config at startup
- `tests/agents/test_connector_registry.py`

**`ConnectorRegistry` design:**
```python
class ConnectorRegistry:
    def __init__(self):
        self._connectors: dict[str, BaseConnector] = {}
        self._health: dict[str, bool] = {}

    def register(self, source_id: str, connector: BaseConnector) -> None:
        self._connectors[source_id] = connector
        self._health[source_id] = True

    def get(self, source_id: str) -> BaseConnector:
        if source_id not in self._connectors:
            raise ConnectorNotFoundError(source_id)
        return self._connectors[source_id]

    def is_active(self, source_id: str) -> bool:
        return (
            source_id in self._connectors
            and self._health.get(source_id, False)
        )

    def active_source_ids(self) -> list[str]:
        return [sid for sid in self._connectors if self._health.get(sid, False)]
```

**`ConnectorLoader` — populates registry at app startup:**
```python
class ConnectorLoader:
    async def load(
        self,
        registry: ConnectorRegistry,
        db_session: AsyncSession,
        vault_client: VaultClient,
    ) -> None:
        configs = await ConnectorConfigRepository(db_session).find_active()
        for config in configs:
            connector_cls = CONNECTOR_CLASS_MAP[config.connector_type]
            credentials = await vault_client.read(config.credentials_vault_path)
            connector = connector_cls(config=config, credentials=credentials)
            registry.register(config.source_id, connector)
```

**`CONNECTOR_CLASS_MAP` — connector type → class mapping:**
```python
CONNECTOR_CLASS_MAP: dict[str, type[BaseConnector]] = {
    "github":     GitHubConnector,
    "confluence": ConfluenceConnector,
    "jira":       JiraConnector,
    "grafana":    GrafanaConnector,
}
```

**Health-check background task (30 s polling):**
```python
async def _health_check_loop(registry: ConnectorRegistry):
    while True:
        for source_id, connector in registry._connectors.items():
            try:
                healthy = await asyncio.wait_for(connector.health_check(), timeout=5.0)
                registry._health[source_id] = healthy
            except Exception:
                registry._health[source_id] = False
        await asyncio.sleep(30)
```
Started in FastAPI lifespan as a background `asyncio.Task`. Unhealthy connectors are automatically excluded from dispatch without requiring a deployment.

**Dynamic re-registration on connector config change:**
Subscribes to Redis pub/sub channel `contextiq:connector_config:changed` (published by Admin API — TASK-US002-02 pattern). On event: reload the changed connector from DB without restarting the service.

## Acceptance Criteria

- [ ] `registry.get("github:myorg/myrepo")` returns the registered `GitHubConnector` instance
- [ ] `registry.is_active("jira:myproject")` returns `False` when health check last failed
- [ ] `ConnectorLoader.load()` registers all `status=active` connectors from DB at startup
- [ ] Health-check loop marks a connector unhealthy within 35 s of it becoming unresponsive (30 s poll + 5 s timeout)
- [ ] Unhealthy connector is skipped by `ParallelConnectorDispatcher` (not dispatched, not in `failed_sources`)
- [ ] Dynamic re-registration: admin activates a new connector → it is available for dispatch within 30 s (no restart)
- [ ] Unit tests cover: registry get, not-found error, is_active with healthy/unhealthy state, loader with 3 config rows

## Dependencies

- EP-007 US-021 (BaseConnector interface — `health_check()` and `fetch()` required methods)
- EP-007 US-025 (connector config stored in PostgreSQL `connector_config` table)
- EP-TECH-002 US-047 (Vault client for credential injection)
- TASK-US007-01 (`ConnectorRegistry` injected into `ParallelConnectorDispatcher`)

## Definition of Done

- [ ] `ConnectorRegistry` and `ConnectorLoader` registered as FastAPI application-level singletons in lifespan
- [ ] Health-check background task started and cancelled cleanly on shutdown
- [ ] Unit coverage ≥ 85% for `connector_registry.py` and `connector_loader.py`
- [ ] Integration test: loader reads 3 active configs from a test DB → all 3 registered and `is_active == True`
