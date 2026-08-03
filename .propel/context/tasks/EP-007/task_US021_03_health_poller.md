# TASK-US021-03 — `ConnectorHealthPoller`: 30-Second Background Health Check

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US021-03 |
| User Story | US-021 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ConnectorHealthPoller` — a background `asyncio.Task` that calls `health_check()` on every registered connector every 30 seconds. When a connector reports `healthy=False`, it is disabled in `ConnectorRegistry` and a Prometheus metric is emitted. The poller starts in the FastAPI lifespan and is cancelled cleanly on shutdown.

## Implementation Details

**Technology:** Python 3.11+, `asyncio`, Prometheus (`prometheus-client>=0.20`)

**File locations:**
- `src/connector_sdk/health_poller.py` — `ConnectorHealthPoller`
- `src/connector_sdk/metrics.py` — Prometheus metrics (extend if file exists; create if not)
- `tests/connector_sdk/test_health_poller.py`

**Prometheus metrics:**

```python
# src/connector_sdk/metrics.py
from prometheus_client import Counter, Gauge

connector_health_checks_total = Counter(
    "connector_health_checks_total",
    "Total health check calls per connector and outcome",
    ["connector_id", "status"],   # status: "healthy" | "unhealthy"
)

connectors_enabled_gauge = Gauge(
    "connectors_enabled_total",
    "Number of connectors currently in enabled state",
)
```

**`ConnectorHealthPoller`:**

```python
# src/connector_sdk/health_poller.py
import asyncio
import logging
from datetime import datetime, timezone
from src.connector_sdk.registry import ConnectorRegistry
from src.connector_sdk.metrics  import connector_health_checks_total, connectors_enabled_gauge

_log = logging.getLogger(__name__)

POLL_INTERVAL_S: int = 30   # US-021 AC-4: polled every 30 s

class ConnectorHealthPoller:
    def __init__(self, registry: ConnectorRegistry, interval_s: int = POLL_INTERVAL_S) -> None:
        self._registry   = registry
        self._interval_s = interval_s
        self._task:      asyncio.Task | None = None

    def start(self) -> None:
        """Start the background polling loop. Idempotent."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop(), name="connector_health_poller")

    def stop(self) -> None:
        """Cancel the polling task. Called from FastAPI lifespan teardown."""
        if self._task and not self._task.done():
            self._task.cancel()

    async def _poll_loop(self) -> None:
        while True:
            await self._poll_once()
            await asyncio.sleep(self._interval_s)

    async def _poll_once(self) -> None:
        """Poll all registered connectors; update registry + metrics."""
        for record in self._registry.records():
            try:
                status = await record.instance.health_check()
            except Exception as exc:
                # health_check() must not raise — if it does, treat as unhealthy
                _log.error(
                    "health_check_raised",
                    extra={"connector_id": record.connector_id, "error": str(exc)},
                )
                from src.connector_sdk.schemas.health import HealthStatus
                status = HealthStatus(
                    healthy    = False,
                    message    = f"health_check() raised: {exc}",
                    checked_at = datetime.now(tz=timezone.utc),
                )

            label = "healthy" if status.healthy else "unhealthy"
            connector_health_checks_total.labels(
                connector_id = record.connector_id,
                status       = label,
            ).inc()

            if not status.healthy:
                _log.warning(
                    "connector_disabled",
                    extra={
                        "connector_id": record.connector_id,
                        "message":      status.message,
                    },
                )

            self._registry.set_health(
                connector_id = record.connector_id,
                healthy      = status.healthy,
                checked_at   = status.checked_at,
            )

        # Recompute enabled gauge after all records updated
        connectors_enabled_gauge.set(len(self._registry.all_enabled()))
```

**Lifespan integration (extend existing, do NOT replace):**

```python
# src/gateway/main.py
from src.connector_sdk.health_poller import ConnectorHealthPoller

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup (registry.load()) ...
    poller = ConnectorHealthPoller(registry=app.state.connector_registry)
    poller.start()
    app.state.connector_health_poller = poller
    yield
    poller.stop()
```

**Shutdown behaviour:**

`poller.stop()` calls `task.cancel()`. `asyncio.sleep()` in `_poll_loop` is an awaitable that raises `asyncio.CancelledError` immediately on cancellation, exiting the loop cleanly. `CancelledError` must not be caught inside `_poll_loop` — it must propagate to allow clean task termination.

**Poll interval configurability:**

`POLL_INTERVAL_S=30` is the default. The `ConnectorHealthPoller` accepts `interval_s` at construction time so tests can use `interval_s=0` (immediate) without patching globals.

## Acceptance Criteria

- [ ] `_poll_once()` calls `health_check()` on all records in the registry
- [ ] After `_poll_once()` with an unhealthy connector, `ConnectorRegistry.get(connector_id)` returns `None`
- [ ] `connector_health_checks_total` counter increments with `status="unhealthy"` on failure
- [ ] `connector_health_checks_total` counter increments with `status="healthy"` on success
- [ ] `connectors_enabled_gauge` reflects the correct enabled count after each poll
- [ ] `health_check()` raising an exception is caught; connector marked unhealthy; no uncaught exception
- [ ] `poller.stop()` cancels the background task without `CancelledError` propagation to the event loop

## Dependencies

- TASK-US021-01 (`HealthStatus` — returned by `health_check()`)
- TASK-US021-02 (`ConnectorRegistry.records()`, `set_health()`, `all_enabled()`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `AsyncMock` for `health_check()`; no `asyncio.sleep()` in tests
- [ ] `mypy --strict` passes; no `ruff` lint errors
