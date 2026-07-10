# TASK-US022-03 — `GitHubConnector.fetch()`: Results Mapping to `ConnectorResult`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US022-03 |
| User Story | US-022 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `GitHubConnector.fetch()` — the method that translates a `ConnectorQuery` into a GitHub Code Search API call, enriches each result with the file's last commit SHA and timestamp via a secondary commits API call, and maps everything to the `ConnectorResult` / `ResultMetadata` schema defined in TASK-US021-01. Results must be returned within 2 seconds for ≤ 50 files.

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]`, `asyncio`

**File locations:**
- `src/connectors/github/connector.py` — `GitHubConnector.fetch()` (extend skeleton from TASK-US022-01)
- `src/connectors/github/content_client.py` — `GitHubContentClient` (fetches file content + commit metadata)
- `tests/connectors/github/test_github_fetch.py`

**`GitHubContentClient` — content + commit enrichment:**

```python
# src/connectors/github/content_client.py
import httpx
from datetime import datetime, timezone
from src.connectors.github.config import GitHubConnectorConfig

class GitHubContentClient:
    """Fetches raw file content and last-commit metadata for a given blob URL."""

    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def fetch_content_and_commit(
        self,
        client:      httpx.AsyncClient,
        repo:        str,
        file_path:   str,
        auth_header: dict[str, str],
    ) -> tuple[str, str, datetime]:
        """
        Returns (content_excerpt, last_commit_sha, committed_at).
        Content excerpt is truncated to 2000 chars — full content is indexed by EP-008.
        """
        headers = {
            **auth_header,
            "Accept":           "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Fetch file content (raw)
        content_url = f"{self._config.base_url}/repos/{repo}/contents/{file_path}"
        content_resp = await client.get(content_url, headers={**headers, "Accept": "application/vnd.github.raw+json"})
        content_resp.raise_for_status()
        excerpt = content_resp.text[:2000]

        # Fetch last commit for this file
        commits_url = f"{self._config.base_url}/repos/{repo}/commits"
        commits_resp = await client.get(
            commits_url,
            params  = {"path": file_path, "per_page": 1},
            headers = headers,
        )
        commits_resp.raise_for_status()
        commits = commits_resp.json()
        if commits:
            sha          = commits[0]["sha"]
            committed_at = datetime.fromisoformat(
                commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00")
            )
        else:
            sha          = ""
            committed_at = datetime.now(tz=timezone.utc)

        return excerpt, sha, committed_at
```

**`GitHubConnector.fetch()`:**

```python
# src/connectors/github/connector.py  — extend existing class
import asyncio
import httpx
from datetime import datetime, timezone
from src.connector_sdk.schemas.query   import ConnectorQuery
from src.connector_sdk.schemas.result  import ConnectorResult, ResultMetadata
from src.connectors.github.search_client  import GitHubSearchClient
from src.connectors.github.content_client import GitHubContentClient

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        """
        Search GitHub code; enrich each result with content excerpt + commit metadata.
        Enforces 2-second total latency budget via asyncio.wait_for().
        """
        return await asyncio.wait_for(
            self._fetch_inner(query),
            timeout = 2.0,   # US-022 AC-7
        )

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        search_client  = GitHubSearchClient(self._config)
        content_client = GitHubContentClient(self._config)
        auth           = self._auth_header()

        items = await search_client.search_code(
            query       = query.query,
            repos       = self._config.repos,
            auth_header = auth,
            max_results = query.max_results,
        )

        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            tasks = [
                content_client.fetch_content_and_commit(
                    client      = client,
                    repo        = item.repository,
                    file_path   = item.path,
                    auth_header = auth,
                )
                for item in items
            ]
            enriched = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[ConnectorResult] = []
        for item, enrichment in zip(items, enriched):
            if isinstance(enrichment, Exception):
                continue   # skip files that could not be enriched; do not fail the batch
            excerpt, commit_sha, committed_at = enrichment

            # Derive branch from filters; default to "main" if not specified
            branch = query.filters.get("branch", "main")

            results.append(ConnectorResult(
                source_id  = f"github:{item.repository}:{item.sha}",
                content    = excerpt,
                metadata   = ResultMetadata(
                    source_url    = item.html_url,
                    author        = None,       # EP-008 can enrich with blame data
                    last_modified = committed_at,
                    extra         = {
                        "file_path":   item.path,
                        "repository":  item.repository,
                        "branch":      branch,
                        "commit_sha":  commit_sha,
                    },
                ),
                fetched_at = datetime.now(tz=timezone.utc),
            ))

        return results
```

**`source_id` stability:**

`github:{repository}:{blob_sha}` is stable for a given file at a given commit. A changed file will produce a new `source_id`, enabling EP-008 to detect stale index entries during sync.

**Concurrent enrichment:**

`asyncio.gather(*tasks)` fetches content and commits for all search results concurrently within a single `httpx.AsyncClient` session, keeping the total latency close to one RTT rather than N×RTT. With `max_results=50` and typical GitHub API p50 < 100 ms, total fetch time stays well under 2 seconds.

## Acceptance Criteria

- [ ] `fetch()` returns a `list[ConnectorResult]` with `source_id` matching `github:{repo}:{sha}` pattern
- [ ] Each `ConnectorResult.metadata.extra` contains `file_path`, `repository`, `branch`, `commit_sha`
- [ ] `fetch()` raises `asyncio.TimeoutError` when total enrichment exceeds 2 s (mocked slow responses)
- [ ] Enrichment failures for individual files are swallowed; other results are returned
- [ ] `fetch()` raises `ConnectorAuthError` when `authenticate()` has not been called
- [ ] `len(results) <= query.max_results` always holds

## Dependencies

- TASK-US022-01 (`GitHubConnector` skeleton, `_auth_header()`, `GitHubConnectorConfig`)
- TASK-US022-02 (`GitHubSearchClient.search_code()`)
- TASK-US021-01 (`ConnectorQuery`, `ConnectorResult`, `ResultMetadata`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `respx` or `httpx.MockTransport`; no live GitHub API calls in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
