# TASK-US023-02 — `ConfluenceCQLClient`: CQL Search API with Space Filtering

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US023-02 |
| User Story | US-023 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ConfluenceCQLClient` — the HTTP client that queries the Confluence Content Search API using CQL (Confluence Query Language). It returns raw page data for all matching results, including page title, body excerpt, space key, URL, last-modified timestamp, and author — satisfying US-023 AC-2 and AC-3.

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]>=0.27`

**File locations:**
- `src/connectors/confluence/cql_client.py` — `ConfluenceCQLClient`, `ConfluencePageItem`
- `tests/connectors/confluence/test_confluence_cql_client.py`

**`ConfluencePageItem` — raw API response row:**

```python
# src/connectors/confluence/cql_client.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class ConfluencePageItem(BaseModel):
    """One result from the Confluence CQL search response."""
    model_config = ConfigDict(frozen=True)

    page_id:      str
    title:        str
    space_key:    str
    url:          str           # absolute URL to the Confluence page
    body_excerpt: str           # truncated body storage value (≤ 5 000 chars raw)
    author:       str | None    # display name; None if anonymous or unavailable
    last_modified: datetime
```

**`ConfluenceCQLClient`:**

```python
# src/connectors/confluence/cql_client.py
import httpx
from src.connectors.confluence.config import ConfluenceConnectorConfig

class ConfluenceCQLClient:
    """
    Queries the Confluence REST v1 Search endpoint.
    Compatible with both Cloud (/wiki/rest/api/content/search) and
    Data Center (/rest/api/content/search) via base_url + path mapping.
    """

    _CLOUD_SEARCH_PATH = "/wiki/rest/api/content/search"
    _DC_SEARCH_PATH    = "/rest/api/content/search"

    def __init__(self, config: ConfluenceConnectorConfig) -> None:
        self._config = config

    def _search_url(self) -> str:
        from src.connectors.confluence.config import ConfluenceDeploymentType
        path = (
            self._CLOUD_SEARCH_PATH
            if self._config.deployment_type == ConfluenceDeploymentType.CLOUD
            else self._DC_SEARCH_PATH
        )
        return f"{self._config.base_url.rstrip('/')}{path}"

    def _build_cql(self, query: str, spaces: list[str], extra_clause: str = "") -> str:
        """
        Build a CQL expression.
        Example: type = "page" AND text ~ "auth flow" AND space in ("ENG","ARCH")
        """
        parts = ['type = "page"', f'text ~ "{query}"']
        if spaces:
            space_list = ", ".join(f'"{s}"' for s in spaces)
            parts.append(f"space in ({space_list})")
        if extra_clause:
            parts.append(extra_clause)
        return " AND ".join(parts)

    async def search(
        self,
        query:       str,
        spaces:      list[str],
        auth_headers: dict[str, str],
        max_results: int = 50,
        extra_cql:   str = "",
    ) -> list[ConfluencePageItem]:
        """
        Execute a CQL search and return at most max_results pages.
        The body excerpt is fetched as body.storage.value — raw Confluence storage format.
        """
        cql    = self._build_cql(query, spaces, extra_cql)
        params = {
            "cql":        cql,
            "limit":      min(max_results, 50),   # Confluence default max per page
            "expand":     "body.storage,version,space,history.lastUpdated",
        }
        items: list[ConfluencePageItem] = []

        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            start = 0
            while len(items) < max_results:
                params["start"] = start
                resp = await client.get(self._search_url(), params=params, headers=auth_headers)
                resp.raise_for_status()
                data      = resp.json()
                results   = data.get("results", [])
                if not results:
                    break
                for r in results:
                    items.append(self._parse_item(r))
                    if len(items) >= max_results:
                        break
                if data.get("size", 0) < params["limit"]:
                    break   # no more pages
                start += params["limit"]

        return items

    def _parse_item(self, r: dict) -> ConfluencePageItem:
        from datetime import timezone
        import dateutil.parser   # python-dateutil for ISO-8601 with timezone

        space_key   = r.get("space", {}).get("key", "")
        base        = self._config.base_url.rstrip("/")
        page_path   = r.get("_links", {}).get("webui", "")
        url         = f"{base}/wiki{page_path}" if self._config.deployment_type == "cloud" else f"{base}{page_path}"
        body_raw    = r.get("body", {}).get("storage", {}).get("value", "")
        body_excerpt = body_raw[:5000]   # raw storage XML; stripped to plain text in fetch()
        last_updated = r.get("history", {}).get("lastUpdated", {}).get("when", "")
        last_modified = dateutil.parser.isoparse(last_updated) if last_updated else None

        contributor = r.get("history", {}).get("lastUpdated", {}).get("by", {})
        author      = contributor.get("displayName") or contributor.get("username")

        return ConfluencePageItem(
            page_id       = r.get("id", ""),
            title         = r.get("title", ""),
            space_key     = space_key,
            url           = url,
            body_excerpt  = body_excerpt,
            author        = author,
            last_modified = last_modified,
        )
```

**Cloud vs. Data Center API path differences:**

| | Cloud | Data Center |
|---|---|---|
| Search endpoint | `/wiki/rest/api/content/search` | `/rest/api/content/search` |
| Web UI URL prefix | `{base_url}/wiki{webui}` | `{base_url}{webui}` |
| Auth | Basic (email + API token) | Bearer PAT |

Both use identical CQL syntax and response shapes; the client switches only on URL path and auth header construction.

**CQL injection guard:**

`query` is user-supplied text embedded in `text ~ "{query}"`. CQL does not support parameterised queries natively, but the `~` contains-operator treats the value as a phrase; double-quote characters inside the query are escaped:

```python
def _sanitise_cql_value(self, value: str) -> str:
    return value.replace('"', '\\"').replace("\\", "\\\\")[:500]
```

Applied to `query` before CQL construction. This prevents CQL injection via crafted query strings.

## Acceptance Criteria

- [ ] `search()` returns a list of `ConfluencePageItem` with all 6 fields populated
- [ ] Cloud search URL is `{base_url}/wiki/rest/api/content/search`
- [ ] Data Center search URL is `{base_url}/rest/api/content/search`
- [ ] `_build_cql()` produces `type = "page" AND text ~ "..."` with space-in clause when spaces non-empty
- [ ] A double-quote in the query is escaped as `\"` in the CQL string
- [ ] `max_results=5` returns at most 5 items even when the API page contains 50

## Dependencies

- TASK-US023-01 (`ConfluenceConnectorConfig`, `ConfluenceDeploymentType`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `respx`; both Cloud and Data Center URL paths tested
- [ ] CQL injection test: query `"arch" AND type = "blogpost"` → escaped correctly
- [ ] `mypy --strict` passes; no `ruff` lint errors
