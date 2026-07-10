# TASK-US024-02 — `JiraConnector.fetch()`, JQL Search Client, and `health_check()`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US024-02 |
| User Story | US-024 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `JiraSearchClient` (JQL query execution against the Jira REST API v3), `JiraConnector.fetch()` (maps issue fields to `ConnectorResult`), and `JiraConnector.health_check()` (probes `/rest/api/3/myself`). Results include issue key, summary, status, priority, assignee, and description excerpt. `fetch()` must complete within 3 seconds (US-024 AC-6).

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]>=0.27`

**File locations:**
- `src/connectors/jira/search_client.py` — `JiraSearchClient`, `JiraIssueItem`
- `src/connectors/jira/connector.py` — `JiraConnector.fetch()`, `health_check()` (extend skeleton)
- `tests/connectors/jira/test_jira_fetch.py`

**`JiraIssueItem` — raw API response row:**

```python
# src/connectors/jira/search_client.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class JiraIssueItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    issue_key:    str         # e.g. "OPS-1234"
    summary:      str
    status:       str         # e.g. "In Progress"
    priority:     str | None  # e.g. "High"
    assignee:     str | None  # display name; None if unassigned
    description:  str         # Atlassian Document Format rendered to plain text (≤ 1000 chars)
    updated:      datetime
    url:          str         # https://{base_url}/browse/{issue_key}
```

**`JiraSearchClient`:**

```python
# src/connectors/jira/search_client.py
import httpx
from src.connectors.jira.config import JiraConnectorConfig

class JiraSearchClient:
    def __init__(self, config: JiraConnectorConfig) -> None:
        self._config = config

    def _build_jql(self, query: str, filters: dict[str, str]) -> str:
        """
        Expand default_jql template and optionally append free-text search.
        Escapes single quotes in the query to prevent JQL injection.
        """
        safe_query = query.replace("'", "\\'").replace('"', '\\"')[:500]
        projects   = ", ".join(self._config.projects) or "ALL"
        base_jql   = self._config.default_jql.format(projects=projects)
        if safe_query:
            return f'({base_jql}) AND text ~ "{safe_query}"'
        return base_jql

    async def search(
        self,
        query:        str,
        auth_headers: dict[str, str],
        filters:      dict[str, str],
        max_results:  int = 50,
    ) -> list[JiraIssueItem]:
        jql    = self._build_jql(query, filters)
        params = {
            "jql":        jql,
            "maxResults": min(max_results, 100),
            "fields":     "summary,status,priority,assignee,description,updated",
        }
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            resp = await client.get(
                f"{self._config.base_url}/rest/api/3/search",
                params  = params,
                headers = auth_headers,
            )
            resp.raise_for_status()
            issues = resp.json().get("issues", [])

        return [self._parse_issue(i) for i in issues[:max_results]]

    def _parse_issue(self, raw: dict) -> JiraIssueItem:
        import dateutil.parser
        fields      = raw.get("fields", {})
        status      = fields.get("status", {}).get("name", "Unknown")
        priority    = (fields.get("priority") or {}).get("name")
        assignee    = (fields.get("assignee") or {}).get("displayName")
        description = self._extract_description(fields.get("description"))
        updated_str = fields.get("updated", "")
        updated     = dateutil.parser.isoparse(updated_str) if updated_str else None
        issue_key   = raw.get("key", "")
        return JiraIssueItem(
            issue_key   = issue_key,
            summary     = fields.get("summary", ""),
            status      = status,
            priority    = priority,
            assignee    = assignee,
            description = description,
            updated     = updated,
            url         = f"{self._config.base_url}/browse/{issue_key}",
        )

    @staticmethod
    def _extract_description(adf: dict | None) -> str:
        """
        Extract plain text from Atlassian Document Format (ADF).
        ADF is a nested JSON structure; recursively collect 'text' leaf nodes.
        Returns at most 1 000 characters.
        """
        if adf is None:
            return ""
        parts: list[str] = []

        def walk(node: dict) -> None:
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []):
                walk(child)

        walk(adf)
        return " ".join(parts)[:1000]
```

**`JiraConnector.fetch()` and `health_check()`:**

```python
# src/connectors/jira/connector.py  — extend existing class
import asyncio
from datetime import datetime, timezone
from src.connector_sdk.schemas.query  import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.health import HealthStatus
from src.connectors.jira.search_client import JiraSearchClient

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        return await asyncio.wait_for(self._fetch_inner(query), timeout=3.0)  # US-024 AC-6

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        client = JiraSearchClient(self._config)
        items  = await client.search(
            query        = query.query,
            auth_headers = self._auth_headers(),
            filters      = query.filters,
            max_results  = query.max_results,
        )
        now = datetime.now(tz=timezone.utc)
        return [
            ConnectorResult(
                source_id  = f"jira:{item.issue_key}",
                content    = f"[{item.issue_key}] {item.summary}\n{item.description}",
                metadata   = ResultMetadata(
                    source_url    = item.url,
                    author        = item.assignee,
                    last_modified = item.updated,
                    extra         = {
                        "issue_key": item.issue_key,
                        "status":    item.status,
                        "priority":  item.priority or "None",
                    },
                ),
                fetched_at = now,
            )
            for item in items
        ]

    async def health_check(self) -> HealthStatus:
        now = datetime.now(tz=timezone.utc)
        try:
            if self._credential is None:
                return HealthStatus(healthy=False, message="Not authenticated", checked_at=now)
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._config.base_url}/rest/api/3/myself",
                    headers=self._auth_headers(),
                )
            if resp.status_code == 200:
                account_id = resp.json().get("accountId", "unknown")
                return HealthStatus(healthy=True, message=f"Jira authenticated as {account_id}", checked_at=now)
            return HealthStatus(healthy=False, message=f"Jira /myself returned HTTP {resp.status_code}", checked_at=now)
        except Exception as exc:
            return HealthStatus(healthy=False, message=f"{type(exc).__name__}: {str(exc)[:150]}", checked_at=now)
```

**JQL injection guard:**

`safe_query = query.replace("'", "\\'").replace('"', '\\"')[:500]` prevents a crafted query like `x" OR project = SECRET AND "` from escaping the CQL text-match clause. Applied before embedding in `text ~ "{safe_query}"`.

**ADF plain-text extraction:**

Jira REST API v3 returns issue descriptions as ADF (Atlassian Document Format) JSON, not plain text. `_extract_description()` recursively collects `type="text"` leaf nodes. This avoids a dependency on Atlassian's ADF renderer library while producing readable content for indexing.

## Acceptance Criteria

- [ ] `fetch()` returns `list[ConnectorResult]` with `source_id` matching `jira:{issue_key}`
- [ ] `metadata.extra` contains `issue_key`, `status`, and `priority`
- [ ] `metadata.author` is populated with the assignee's display name when present
- [ ] `fetch()` raises `asyncio.TimeoutError` when total response exceeds 3 s (mocked)
- [ ] `health_check()` returns `healthy=True` when `/myself` returns 200
- [ ] `health_check()` returns `healthy=False` and does not raise on HTTP 401
- [ ] JQL injection test: query `" OR project = SECRET` is escaped before CQL embedding
- [ ] ADF description with nested paragraph nodes extracts all leaf text correctly

## Dependencies

- TASK-US024-01 (`JiraConnector` skeleton, `_auth_headers()`, `JiraConnectorConfig`)
- TASK-US021-01 (`ConnectorQuery`, `ConnectorResult`, `ResultMetadata`, `HealthStatus`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `respx`; no live Jira in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
