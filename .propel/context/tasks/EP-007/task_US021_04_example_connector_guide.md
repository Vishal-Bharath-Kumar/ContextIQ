# TASK-US021-04 — Example Connector and Developer Guide

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US021-04 |
| User Story | US-021 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Docs / SDK |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Provide a working example connector (an in-memory echo connector) and a developer guide covering the full connector authoring lifecycle: implementing `BaseConnector`, packaging with entry-point registration, running the test scaffold, and submitting a connector for review. Satisfies US-021 AC-5.

## Implementation Details

**File locations:**
- `examples/connectors/echo_connector/connector.py` — `EchoConnector` (working reference)
- `examples/connectors/echo_connector/pyproject.toml` — entry-point registration
- `docs/connector-sdk.md` — developer guide (Markdown)

**`EchoConnector` — working reference implementation:**

```python
# examples/connectors/echo_connector/connector.py
"""
EchoConnector — minimal reference implementation of BaseConnector.

Echoes the query text back as a single ConnectorResult.
No external I/O; safe to run in CI and local dev without credentials.
"""
from datetime import datetime, timezone
from src.connector_sdk.base                  import BaseConnector
from src.connector_sdk.schemas.query         import ConnectorQuery
from src.connector_sdk.schemas.result        import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.sync          import SyncResult
from src.connector_sdk.schemas.health        import HealthStatus


class EchoConnector(BaseConnector):
    """Returns the query text as a result; always healthy; no credentials required."""

    async def authenticate(self) -> None:
        # No credentials needed for the echo connector
        pass

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        return [
            ConnectorResult(
                source_id  = f"echo:{hash(query.query) & 0xFFFFFF:06x}",
                content    = f"Echo: {query.query}",
                metadata   = ResultMetadata(source_url=None, author="echo-connector"),
                fetched_at = datetime.now(tz=timezone.utc),
            )
        ]

    async def sync(self) -> SyncResult:
        return SyncResult(
            items_processed = 0,
            items_failed    = 0,
            last_sync_at    = datetime.now(tz=timezone.utc),
        )

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            healthy    = True,
            message    = "EchoConnector is always healthy",
            checked_at = datetime.now(tz=timezone.utc),
        )
```

**Entry-point registration (`examples/connectors/echo_connector/pyproject.toml`):**

```toml
[build-system]
requires      = ["hatchling"]
build-backend = "hatchling.build"

[project]
name    = "contextiq-echo-connector"
version = "0.1.0"
requires-python = ">=3.11"
dependencies    = ["contextiq-connector-sdk"]

[project.entry-points."contextiq.connectors"]
echo = "echo_connector.connector:EchoConnector"
```

**`docs/connector-sdk.md` — developer guide outline:**

The guide covers these sections (full prose to be written by the technical writer; structure is specified here for completeness):

1. **Overview** — what a connector is; how it fits into the ContextIQ retrieval pipeline
2. **Prerequisites** — Python 3.11+, `contextiq-connector-sdk` package, Vault access for credentials
3. **Quick start** — copy `examples/connectors/echo_connector/`; rename; implement 4 methods
4. **`BaseConnector` API reference** — parameter types, return types, error contracts for each method
5. **Entry-point registration** — `pyproject.toml` snippet; `connector_id` naming convention (lowercase, hyphens)
6. **Credential handling** — read from Vault via `hvac`; never hardcode; never log credential values
7. **Incremental sync** — store `last_sync_at` in the connector config store (PostgreSQL); fetch `since=last_sync_at`
8. **`health_check()` contract** — must not raise; must return within 5 s; include auth validation
9. **Running the test scaffold** — `pytest tests/connector_sdk/` with the provided `BaseConnectorTestCase`
10. **Submission checklist** — required before a connector is merged to `main`

## Acceptance Criteria

- [ ] `EchoConnector` passes all 4 methods of `BaseConnectorTestCase` (TASK-US021-05) without modification
- [ ] `EchoConnector` is importable and instantiable with no dependencies beyond `contextiq-connector-sdk`
- [ ] `examples/connectors/echo_connector/pyproject.toml` registers `EchoConnector` under `contextiq.connectors`
- [ ] `docs/connector-sdk.md` covers all 10 sections listed above
- [ ] The developer guide references `BaseConnectorTestCase` and shows a minimal test subclass example

## Dependencies

- TASK-US021-01 (`BaseConnector`, `ConnectorQuery`, `ConnectorResult`, `SyncResult`, `HealthStatus`)
- TASK-US021-05 (`BaseConnectorTestCase` — used as the validation harness for `EchoConnector`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `EchoConnector` included in CI test run via `pytest examples/`
- [ ] `docs/connector-sdk.md` reviewed by one engineer who has not previously read it (comprehension check)
- [ ] `mypy --strict` passes on `echo_connector/connector.py`
