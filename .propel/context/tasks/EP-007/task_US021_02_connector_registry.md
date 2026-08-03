# TASK-US021-02 — Entry-Point Auto-Discovery and `ConnectorRegistry`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US021-02 |
| User Story | US-021 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend / SDK |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ConnectorRegistry` — the component that discovers, instantiates, and manages all registered connectors at application startup using Python's `importlib.metadata` entry-point mechanism. Third-party connector packages register themselves under the `contextiq.connectors` group in their `pyproject.toml`; the platform loads them without any core code changes.

## Implementation Details

**Technology:** Python 3.11+, `importlib.metadata`, Pydantic v2

**File locations:**
- `src/connector_sdk/registry.py` — `ConnectorRegistry`, `ConnectorRecord`
- `src/connector_sdk/discovery.py` — `discover_connectors()` (pure function; testable in isolation)
- `pyproject.toml` — `[project.entry-points."contextiq.connectors"]` for first-party connectors
- `tests/connector_sdk/test_registry.py`

**Entry-point registration convention:**

Third-party connector packages declare their connector in `pyproject.toml`:

```toml
[project.entry-points."contextiq.connectors"]
github     = "contextiq_github_connector.connector:GitHubConnector"
confluence = "contextiq_confluence_connector.connector:ConfluenceConnector"
```

The entry-point name becomes the connector's stable `connector_id`. Entry-point values are dotted import paths to `BaseConnector` subclasses.

**`discover_connectors()`:**

```python
# src/connector_sdk/discovery.py
import importlib.metadata
import importlib
import inspect
from src.connector_sdk.base import BaseConnector

def discover_connectors() -> dict[str, type[BaseConnector]]:
    """
    Load all entry points under 'contextiq.connectors'.
    Returns a dict of {connector_id: ConnectorClass}.
    Skips entries that fail to import or do not subclass BaseConnector.
    """
    discovered: dict[str, type[BaseConnector]] = {}
    eps = importlib.metadata.entry_points(group="contextiq.connectors")

    for ep in eps:
        try:
            cls = ep.load()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "connector_discovery_failed",
                extra={"entry_point": ep.name, "error": str(exc)},
            )
            continue

        if not (inspect.isclass(cls) and issubclass(cls, BaseConnector)):
            logging.getLogger(__name__).warning(
                "connector_not_a_baseconnector",
                extra={"entry_point": ep.name, "cls": repr(cls)},
            )
            continue

        discovered[ep.name] = cls

    return discovered
```

**`ConnectorRecord`:**

```python
# src/connector_sdk/registry.py
from dataclasses import dataclass, field
from datetime import datetime
from src.connector_sdk.base import BaseConnector

@dataclass
class ConnectorRecord:
    connector_id: str
    cls:          type[BaseConnector]
    instance:     BaseConnector
    enabled:      bool          = True
    last_health:  bool | None   = None
    last_checked: datetime | None = None
```

**`ConnectorRegistry`:**

```python
class ConnectorRegistry:
    def __init__(self) -> None:
        self._records: dict[str, ConnectorRecord] = {}

    async def load(self, connector_classes: dict[str, type[BaseConnector]] | None = None) -> None:
        """
        Discover connectors (or use injected dict for tests), instantiate each,
        and call authenticate(). Connectors that fail authenticate() are registered
        but marked enabled=False.
        """
        classes = connector_classes or discover_connectors()
        for connector_id, cls in classes.items():
            instance = cls()
            enabled  = True
            try:
                await instance.authenticate()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "connector_auth_failed",
                    extra={"connector_id": connector_id, "error": str(exc)},
                )
                enabled = False
            self._records[connector_id] = ConnectorRecord(
                connector_id = connector_id,
                cls          = cls,
                instance     = instance,
                enabled      = enabled,
            )

    def get(self, connector_id: str) -> BaseConnector | None:
        record = self._records.get(connector_id)
        return record.instance if (record and record.enabled) else None

    def all_enabled(self) -> list[BaseConnector]:
        return [r.instance for r in self._records.values() if r.enabled]

    def set_health(self, connector_id: str, healthy: bool, checked_at: datetime) -> None:
        """Called by ConnectorHealthPoller (TASK-US021-03) to update runtime state."""
        if record := self._records.get(connector_id):
            record.last_health  = healthy
            record.last_checked = checked_at
            if not healthy:
                record.enabled = False

    def records(self) -> list[ConnectorRecord]:
        return list(self._records.values())
```

**Singleton registration in FastAPI lifespan:**

```python
# src/gateway/main.py  (extend existing lifespan — do NOT replace)
from src.connector_sdk.registry import ConnectorRegistry

@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = ConnectorRegistry()
    await registry.load()
    app.state.connector_registry = registry
    yield
    # cleanup: no explicit teardown required; connector instances are GC'd
```

## Acceptance Criteria

- [ ] `discover_connectors()` returns only classes that subclass `BaseConnector`
- [ ] A malformed entry point (import error) is logged and skipped — `load()` does not raise
- [ ] A class that does not subclass `BaseConnector` is logged and skipped
- [ ] `ConnectorRegistry.load()` calls `authenticate()` on each discovered class
- [ ] Connectors where `authenticate()` raises are registered with `enabled=False`
- [ ] `ConnectorRegistry.get("unknown_id")` returns `None`
- [ ] `ConnectorRegistry.get()` returns `None` for disabled connectors

## Dependencies

- TASK-US021-01 (`BaseConnector` ABC — import guard uses `issubclass(cls, BaseConnector)`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests inject a `connector_classes` dict (no live entry points in CI)
- [ ] `mypy --strict` passes; no `ruff` lint errors
