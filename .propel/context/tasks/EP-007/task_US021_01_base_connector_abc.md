# TASK-US021-01 — `BaseConnector` Abstract Class and Core SDK Data Models

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US021-01 |
| User Story | US-021 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend / SDK |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define `BaseConnector` — the abstract base class that all connectors (first-party and third-party) must subclass — along with the frozen Pydantic data models that form the public SDK contract: `ConnectorQuery`, `ConnectorResult`, `SyncResult`, and `HealthStatus`. These types are the only cross-cutting dependency for every downstream connector story (US-022, US-023, US-024).

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `abc`

**File locations:**
- `src/connector_sdk/base.py` — `BaseConnector` ABC
- `src/connector_sdk/schemas/__init__.py` — re-exports all public types
- `src/connector_sdk/schemas/query.py` — `ConnectorQuery`
- `src/connector_sdk/schemas/result.py` — `ConnectorResult`, `ResultMetadata`
- `src/connector_sdk/schemas/sync.py` — `SyncResult`
- `src/connector_sdk/schemas/health.py` — `HealthStatus`
- `tests/connector_sdk/test_base_connector.py`

**Core data models:**

```python
# src/connector_sdk/schemas/query.py
from pydantic import BaseModel, ConfigDict, Field

class ConnectorQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    query:       str            = Field(min_length=1, max_length=2000)
    filters:     dict[str, str] = Field(default_factory=dict)
    max_results: int            = Field(default=50, gt=0, le=500)
```

```python
# src/connector_sdk/schemas/result.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class ResultMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_url:   str | None     = None
    author:       str | None     = None
    last_modified: datetime | None = None
    extra:        dict[str, str] = Field(default_factory=dict)

class ConnectorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id:  str             # unique stable identifier for this item
    content:    str             # raw text; chunking happens in EP-008
    metadata:   ResultMetadata
    fetched_at: datetime
```

```python
# src/connector_sdk/schemas/sync.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class SyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    items_processed: int
    items_failed:    int
    last_sync_at:    datetime
    errors:          list[str] = []  # error summaries; no stack traces
```

```python
# src/connector_sdk/schemas/health.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class HealthStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    healthy:    bool
    message:    str       # human-readable; ≤ 200 chars; logged by health poller
    checked_at: datetime
```

**`BaseConnector` ABC:**

```python
# src/connector_sdk/base.py
from abc import ABC, abstractmethod
from src.connector_sdk.schemas.query  import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult
from src.connector_sdk.schemas.sync   import SyncResult
from src.connector_sdk.schemas.health import HealthStatus

class BaseConnector(ABC):
    """
    Abstract base class for all ContextIQ connectors.

    Subclasses must implement: authenticate, fetch, sync, health_check.
    All methods are async-first; synchronous connectors must wrap I/O in
    asyncio.to_thread().
    """

    @abstractmethod
    async def authenticate(self) -> None:
        """
        Acquire and cache credentials for this connector session.
        Raise ConnectorAuthError on failure.
        Called once at startup and re-called by the health poller on auth expiry.
        """
        ...

    @abstractmethod
    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        """
        Retrieve items matching query from the external source.
        Must return within 2 s for ≤ 50 results (NFR-008).
        """
        ...

    @abstractmethod
    async def sync(self) -> SyncResult:
        """
        Perform an incremental sync; fetch only items changed since last sync.
        Emit a DR-005 StateTransitionEvent on completion.
        """
        ...

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """
        Return a HealthStatus. Must not raise — catch all internal errors and
        return HealthStatus(healthy=False, message=str(exc), ...).
        Called every 30 s by ConnectorHealthPoller.
        """
        ...
```

**`ConnectorAuthError`:**

```python
# src/connector_sdk/exceptions.py
class ConnectorAuthError(Exception):
    """Raised by authenticate() when credentials cannot be obtained or validated."""
```

## Acceptance Criteria

- [ ] Instantiating `BaseConnector` directly raises `TypeError` (ABC enforcement)
- [ ] A concrete subclass that omits any abstract method raises `TypeError` on instantiation
- [ ] All 4 schema models are frozen — `model_copy()` required for updates
- [ ] `ConnectorQuery(query="", ...)` raises `ValidationError` (`min_length=1`)
- [ ] `ConnectorQuery(max_results=501)` raises `ValidationError` (`le=500`)
- [ ] `HealthStatus(healthy=False, ...)` constructs without error (unhealthy states are valid)

## Dependencies

- No upstream task dependencies — this is the foundation of EP-007.

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Public API exported from `src/connector_sdk/__init__.py`
- [ ] `mypy --strict` passes; no `ruff` lint errors
