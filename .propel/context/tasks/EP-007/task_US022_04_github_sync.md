# TASK-US022-04 — `GitHubConnector.sync()`: Incremental Sync with `since` Parameter

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US022-04 |
| User Story | US-022 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `GitHubConnector.sync()` — the incremental synchronisation method that fetches only commits and changed files since the last recorded sync timestamp. The `last_sync_at` cursor is read from and written back to the PostgreSQL connector config store. On completion, a DR-005 `StateTransitionEvent` is emitted to the Kafka `contextiq.source.sync` topic so EP-008 can trigger re-indexing.

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]`, SQLAlchemy 2.x async, `aiokafka`

**File locations:**
- `src/connectors/github/sync_client.py` — `GitHubCommitsClient` (commits API calls)
- `src/connectors/github/sync_store.py` — `ConnectorSyncStore` (reads/writes `last_sync_at`)
- `src/connectors/github/connector.py` — `GitHubConnector.sync()` (extend existing class)
- `tests/connectors/github/test_github_sync.py`

**`ConnectorSyncStore` — PostgreSQL cursor:**

```python
# src/connectors/github/sync_store.py
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

class ConnectorSyncStore:
    """
    Reads and writes the last_sync_at timestamp for a connector instance.
    Table: connector_sync_state (connector_id VARCHAR PK, last_sync_at TIMESTAMPTZ).
    Created by EP-DATA-001 migration.
    """
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_last_sync_at(self, connector_id: str) -> datetime | None:
        row = await self._session.execute(
            text("SELECT last_sync_at FROM connector_sync_state WHERE connector_id = :id"),
            {"id": connector_id},
        )
        result = row.fetchone()
        return result[0] if result else None

    async def set_last_sync_at(self, connector_id: str, synced_at: datetime) -> None:
        await self._session.execute(
            text("""
                INSERT INTO connector_sync_state (connector_id, last_sync_at)
                VALUES (:id, :ts)
                ON CONFLICT (connector_id) DO UPDATE SET last_sync_at = EXCLUDED.last_sync_at
            """),
            {"id": connector_id, "ts": synced_at},
        )
        await self._session.commit()
```

**`GitHubCommitsClient` — incremental commits fetch:**

```python
# src/connectors/github/sync_client.py
from datetime import datetime
import httpx
from src.connectors.github.config import GitHubConnectorConfig

class GitHubCommitsClient:
    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def fetch_changed_files(
        self,
        repo:        str,
        since:       datetime,
        auth_header: dict[str, str],
    ) -> list[str]:
        """
        Returns a deduplicated list of file paths changed in `repo` since `since`.
        Uses the /repos/{repo}/commits endpoint with the `since` ISO-8601 parameter.
        """
        headers = {
            **auth_header,
            "Accept":               "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        changed: set[str] = set()
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            page = 1
            while True:
                resp = await client.get(
                    f"{self._config.base_url}/repos/{repo}/commits",
                    params  = {"since": since.isoformat(), "per_page": 100, "page": page},
                    headers = headers,
                )
                resp.raise_for_status()
                commits = resp.json()
                if not commits:
                    break
                for commit in commits:
                    # Fetch commit detail to get file list
                    detail_resp = await client.get(commit["url"], headers=headers)
                    detail_resp.raise_for_status()
                    for file_entry in detail_resp.json().get("files", []):
                        changed.add(file_entry["filename"])
                page += 1
        return list(changed)
```

**`GitHubConnector.sync()`:**

```python
# src/connectors/github/connector.py  — extend existing class
from datetime import datetime, timezone
from src.connector_sdk.schemas.sync import SyncResult

    async def sync(self) -> SyncResult:
        """
        Incremental sync: fetch files changed since last_sync_at.
        Falls back to default_days window when no prior sync exists.
        Emits DR-005 StateTransitionEvent on completion.
        """
        sync_store  = ConnectorSyncStore(self._session)   # injected at construction
        commits_client = GitHubCommitsClient(self._config)
        auth        = self._auth_header()
        now         = datetime.now(tz=timezone.utc)

        last_sync   = await sync_store.get_last_sync_at("github")
        if last_sync is None:
            from datetime import timedelta
            last_sync = now - timedelta(days=self._config.default_days)

        items_processed = 0
        items_failed    = 0
        errors: list[str] = []

        for repo in self._config.repos:
            try:
                changed_paths = await commits_client.fetch_changed_files(
                    repo        = repo,
                    since       = last_sync,
                    auth_header = auth,
                )
                items_processed += len(changed_paths)
            except Exception as exc:
                items_failed += 1
                errors.append(f"{repo}: {type(exc).__name__}: {exc}")

        await sync_store.set_last_sync_at("github", now)
        await self._emit_sync_event(items_processed=items_processed, synced_at=now)

        return SyncResult(
            items_processed = items_processed,
            items_failed    = items_failed,
            last_sync_at    = now,
            errors          = errors,
        )

    async def _emit_sync_event(self, items_processed: int, synced_at: datetime) -> None:
        """Emit DR-005 StateTransitionEvent to contextiq.source.sync Kafka topic."""
        import json
        from src.events.producer import get_kafka_producer   # shared Kafka producer

        event = {
            "event_type":       "source_sync_completed",
            "connector_id":     "github",
            "items_processed":  items_processed,
            "synced_at":        synced_at.isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            "contextiq.source.sync",
            value = json.dumps(event).encode(),
        )
```

**`GitHubConnector` constructor extension:**

```python
# src/connectors/github/connector.py  — extend __init__
from sqlalchemy.ext.asyncio import AsyncSession

class GitHubConnector(BaseConnector):
    def __init__(
        self,
        config:  GitHubConnectorConfig | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self._config   = config or GitHubConnectorConfig()
        self._session  = session          # injected for sync; None in fetch-only usage
        self._token_provider = GitHubTokenProvider(self._config)
        self._credential: GitHubCredential | None = None
```

## Acceptance Criteria

- [ ] `sync()` calls commits API with `since=last_sync_at` when a prior sync exists
- [ ] `sync()` defaults to `now - default_days` when no prior sync record exists
- [ ] `sync()` writes the new `last_sync_at` to `connector_sync_state` after completion
- [ ] `sync()` returns `SyncResult` with `items_processed` ≥ 0 and `items_failed` ≥ 0
- [ ] Per-repo errors are captured in `SyncResult.errors`; sync does not abort on a single repo failure
- [ ] `_emit_sync_event()` sends a message to `contextiq.source.sync` topic
- [ ] `sync()` raises `ConnectorAuthError` when `authenticate()` has not been called

## Dependencies

- TASK-US022-01 (`GitHubConnector` skeleton, `_auth_header()`, `GitHubConnectorConfig`)
- TASK-US021-01 (`SyncResult`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `ConnectorSyncStore`, `GitHubCommitsClient`, and Kafka producer via `AsyncMock`
- [ ] `mypy --strict` passes; no `ruff` lint errors
