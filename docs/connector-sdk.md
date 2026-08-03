# ContextIQ Connector SDK — Developer Guide

## 1. Overview

A **connector** is a self-contained Python package that bridges ContextIQ's retrieval pipeline to a single external knowledge source (e.g., GitHub, Confluence, Jira). At query time, the pipeline calls `fetch()` on the registered connector and incorporates the returned text chunks into its retrieval context. Connectors also support incremental sync (background polling) and health monitoring.

```mermaid
flowchart LR
    Pipeline["ContextIQ Retrieval Pipeline"] -->|ConnectorQuery| Connector
    Connector -->|list[ConnectorResult]| Pipeline
    HealthPoller["ConnectorHealthPoller\n(every 30 s)"] -->|health_check()| Connector
    Scheduler["Sync Scheduler"] -->|sync()| Connector
```

Every connector extends `BaseConnector` and implements exactly four async methods: `authenticate`, `fetch`, `sync`, and `health_check`.

---

## 2. Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| `contextiq-connector-sdk` | current |
| HashiCorp Vault access | for secret storage |
| `pytest` + `pytest-asyncio` | for test scaffold |

Install the SDK into your development environment:

```bash
pip install contextiq-connector-sdk
```

---

## 3. Quick Start

1. Copy the reference example:

    ```bash
    cp -r examples/connectors/echo_connector/ my_connector/
    ```

2. Rename the class to `MyConnector` in `connector.py`.

3. Implement the four abstract methods (see §4).

4. Update `pyproject.toml` with your connector name and entry-point (see §5).

5. Run the test scaffold to verify the contract (see §9).

The `EchoConnector` in `examples/connectors/echo_connector/` is a fully working reference that passes all contract tests with zero external dependencies.

---

## 4. `BaseConnector` API Reference

Import from `src.connector_sdk`:

```python
from src.connector_sdk import BaseConnector, ConnectorQuery, ConnectorResult, SyncResult, HealthStatus
```

### `authenticate(self) -> None`

| | |
|---|---|
| **Called** | Once at startup; re-called by the health poller on auth expiry |
| **Raises** | `ConnectorAuthError` on failure |
| **Side effects** | Cache the credential/session on `self` for use by `fetch()` and `sync()` |

### `fetch(self, query: ConnectorQuery) -> list[ConnectorResult]`

| Parameter | Type | Description |
|---|---|---|
| `query.query` | `str` (1–2000 chars) | Free-text search string |
| `query.filters` | `dict[str, str]` | Optional key/value filters |
| `query.max_results` | `int` (1–500, default 50) | Upper bound on returned items |

**Return contract:**
- Return `list[ConnectorResult]` (may be empty, never `None`).
- Must return within **2 seconds** for ≤ 50 results (NFR-008).
- Each `ConnectorResult` must have a stable, unique `source_id`.

### `sync(self) -> SyncResult`

Performs an incremental sync fetching only items changed since `last_sync_at`.

| Return field | Type | Description |
|---|---|---|
| `items_processed` | `int ≥ 0` | Number of items successfully ingested |
| `items_failed` | `int ≥ 0` | Number of items that failed |
| `last_sync_at` | `datetime` (UTC) | Timestamp of this sync completion |
| `errors` | `list[str]` | Human-readable error summaries; no stack traces |

### `health_check(self) -> HealthStatus`

| Contract | Requirement |
|---|---|
| Must not raise | Catch all internal exceptions |
| Return within | 5 seconds |
| Validates auth | Should verify cached credential is still valid |

| Return field | Type | Description |
|---|---|---|
| `healthy` | `bool` | `True` if the connector is operational |
| `message` | `str` (≤ 200 chars) | Human-readable status; logged by health poller |
| `checked_at` | `datetime` (UTC) | When the probe ran |

---

## 5. Entry-Point Registration

Connectors are discovered via Python package entry-points. In your connector's `pyproject.toml`:

```toml
[build-system]
requires      = ["hatchling"]
build-backend = "hatchling.build"

[project]
name    = "contextiq-my-connector"
version = "0.1.0"
requires-python = ">=3.11"
dependencies    = ["contextiq-connector-sdk"]

[project.entry-points."contextiq.connectors"]
my-connector = "my_connector.connector:MyConnector"
```

**`connector_id` naming convention:** lowercase words separated by hyphens (e.g., `github`, `confluence`, `jira-cloud`). The entry-point key becomes the connector's registry ID.

---

## 6. Credential Handling

Credentials **must** be retrieved from HashiCorp Vault at runtime using the `hvac` client. Never hardcode secrets in source code, configuration files, or environment variables committed to version control.

```python
import hvac

class MyConnector(BaseConnector):
    async def authenticate(self) -> None:
        client = hvac.Client(url=vault_addr, token=vault_token)
        secret = client.secrets.kv.v2.read_secret_version(
            path="connectors/my-connector"
        )
        self._api_key = secret["data"]["data"]["api_key"]
```

**Rules:**
- Never log credential values — log only key names or masked representations.
- Store only the credential on `self`; do not propagate it through return values.
- Re-authenticate when `ConnectorAuthError` is raised inside `fetch()` or `sync()`.

---

## 7. Incremental Sync

Store `last_sync_at` in the connector config store (PostgreSQL) so sync resumes correctly after restarts.

```python
async def sync(self) -> SyncResult:
    last = await self._config_store.get("last_sync_at")  # datetime or None
    items = await self._api.fetch_since(since=last)

    processed, failed = 0, 0
    for item in items:
        try:
            await self._ingest(item)
            processed += 1
        except Exception as exc:
            failed += 1
            errors.append(str(exc))

    now = datetime.now(tz=timezone.utc)
    await self._config_store.set("last_sync_at", now.isoformat())
    return SyncResult(items_processed=processed, items_failed=failed, last_sync_at=now)
```

Pass `since=last_sync_at` as a query parameter to the external API to avoid re-fetching unchanged content.

---

## 8. `health_check()` Contract

The `ConnectorHealthPoller` calls `health_check()` every 30 seconds. Follow these rules strictly:

1. **Must not raise** — wrap the entire body in `try/except Exception`.
2. **Must return within 5 seconds** — use `asyncio.wait_for` with a 4.5-second timeout to leave margin.
3. **Validate auth** — probe the external API with a lightweight call (e.g., `/rate_limit`, `/ping`, `/whoami`) to detect expired credentials early.

```python
async def health_check(self) -> HealthStatus:
    try:
        async with asyncio.timeout(4.5):
            await self._api.ping()
        return HealthStatus(
            healthy=True,
            message="OK",
            checked_at=datetime.now(tz=timezone.utc),
        )
    except Exception as exc:
        return HealthStatus(
            healthy=False,
            message=str(exc)[:200],
            checked_at=datetime.now(tz=timezone.utc),
        )
```

---

## 9. Running the Test Scaffold

The SDK ships `BaseConnectorTestCase` — an abstract pytest class with 6 contract tests. Subclass it with your connector and two fixtures:

```python
# tests/test_my_connector.py
import pytest
from src.connector_sdk.testing import BaseConnectorTestCase, ConnectorQuery
from my_connector.connector import MyConnector

class TestMyConnector(BaseConnectorTestCase):
    @pytest.fixture
    def make_connector(self) -> MyConnector:
        return MyConnector()

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        return ConnectorQuery(query="test query", max_results=5)
```

Run against the connector SDK test suite:

```bash
pytest tests/connector_sdk/ -v
```

The six contract tests that must pass:

| Test | Validates |
|---|---|
| `test_authenticate_does_not_raise` | `authenticate()` completes without exception |
| `test_fetch_returns_list_of_connector_results` | `fetch()` returns `list[ConnectorResult]` with valid fields |
| `test_sync_returns_sync_result` | `sync()` returns `SyncResult` with non-negative counts |
| `test_health_check_returns_health_status` | `health_check()` returns `HealthStatus` with all required fields |
| `test_health_check_does_not_raise_on_repeated_calls` | `health_check()` is safe to call 3× in succession |
| `test_fetch_respects_max_results` | `fetch()` returns ≤ `max_results` items |

`pytest-asyncio` must be configured with `asyncio_mode = "auto"` (already set in the project's `pyproject.toml`).

---

## 10. Submission Checklist

Complete all items before opening a pull request to `main`:

- [ ] `authenticate()`, `fetch()`, `sync()`, `health_check()` all implemented
- [ ] All 6 `BaseConnectorTestCase` contract tests pass with no live network calls (use mocks)
- [ ] `health_check()` catches all exceptions and returns within 5 s
- [ ] `fetch()` returns within 2 s for ≤ 50 results (NFR-008)
- [ ] Credentials fetched from Vault via `hvac`; none hardcoded or logged
- [ ] `pyproject.toml` entry-point registered under `contextiq.connectors` with a lowercase-hyphen `connector_id`
- [ ] `mypy --strict` passes on `connector.py`
- [ ] `ruff check` passes with no errors
- [ ] `last_sync_at` persisted to the PostgreSQL config store in `sync()`
- [ ] PR description references the relevant User Story and links to test results
