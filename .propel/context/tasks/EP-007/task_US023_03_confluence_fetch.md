# TASK-US023-03 — `ConfluenceConnector.fetch()`: Results Mapping and Plain-Text Extraction

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US023-03 |
| User Story | US-023 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `ConfluenceConnector.fetch()` — the method that calls `ConfluenceCQLClient.search()`, strips Confluence storage-format XML from the body excerpt to plain text, and maps each result to the `ConnectorResult` / `ResultMetadata` schema. Results are returned within 2 seconds via `asyncio.wait_for()`.

## Implementation Details

**Technology:** Python 3.11+, `html.parser` (stdlib), `asyncio`

**File locations:**
- `src/connectors/confluence/html_stripper.py` — `strip_confluence_storage()`
- `src/connectors/confluence/connector.py` — `ConfluenceConnector.fetch()` (extend existing class)
- `tests/connectors/confluence/test_confluence_fetch.py`

**`strip_confluence_storage()` — plain-text extraction:**

Confluence storage format is XML with proprietary tags (e.g. `<ac:structured-macro>`, `<ri:attachment>`). The indexing pipeline in EP-008 works on plain text; the connector's responsibility is to produce a readable excerpt, not a pixel-perfect render.

```python
# src/connectors/confluence/html_stripper.py
from html.parser import HTMLParser

class _PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_tags = {"style", "script", "ac:parameter", "ac:default-parameter"}
        self._current_skip: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._skip_tags:
            self._current_skip = tag

    def handle_endtag(self, tag: str) -> None:
        if tag == self._current_skip:
            self._current_skip = None

    def handle_data(self, data: str) -> None:
        if self._current_skip is None:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def plain_text(self) -> str:
        return " ".join(self._parts)


def strip_confluence_storage(html: str) -> str:
    """
    Convert Confluence storage-format XML/HTML to plain text.
    Returns at most 5 000 characters of readable content.
    """
    extractor = _PlainTextExtractor()
    extractor.feed(html)
    return extractor.plain_text()[:5000]
```

**`ConfluenceConnector.fetch()`:**

```python
# src/connectors/confluence/connector.py  — extend existing class
import asyncio
from datetime import datetime, timezone
from src.connector_sdk.schemas.query   import ConnectorQuery
from src.connector_sdk.schemas.result  import ConnectorResult, ResultMetadata
from src.connectors.confluence.cql_client     import ConfluenceCQLClient
from src.connectors.confluence.html_stripper  import strip_confluence_storage

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        return await asyncio.wait_for(
            self._fetch_inner(query),
            timeout = 2.0,   # US-023 AC-7
        )

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        cql_client = ConfluenceCQLClient(self._config)
        spaces     = list(query.filters.get("spaces", "").split(",")) \
                     if query.filters.get("spaces") \
                     else self._config.spaces

        items = await cql_client.search(
            query        = query.query,
            spaces       = spaces,
            auth_headers = self._auth_headers(),
            max_results  = query.max_results,
        )

        results: list[ConnectorResult] = []
        for item in items:
            plain_text = strip_confluence_storage(item.body_excerpt)
            results.append(ConnectorResult(
                source_id  = f"confluence:{item.space_key}:{item.page_id}",
                content    = plain_text,
                metadata   = ResultMetadata(
                    source_url    = item.url,
                    author        = item.author,
                    last_modified = item.last_modified,
                    extra         = {
                        "page_title": item.title,
                        "space_key":  item.space_key,
                        "page_id":    item.page_id,
                    },
                ),
                fetched_at = datetime.now(tz=timezone.utc),
            ))
        return results
```

**`source_id` design:**

`confluence:{space_key}:{page_id}` is stable across page edits (page IDs are immutable in Confluence). A page moved between spaces will produce a new `source_id`, which EP-008 treats as a new document and re-indexes.

**Spaces override via `query.filters`:**

Callers may pass `filters={"spaces": "ENG,ARCH"}` to override the configured default spaces for a single query. If the filter is absent, `self._config.spaces` is used. This enables per-request scope narrowing without reconfiguring the connector.

**Plain-text quality note:**

`strip_confluence_storage()` is a best-effort stripper sufficient for indexing; it does not render Confluence macros (e.g. code blocks, tables). EP-008 may apply further normalisation during chunking. The 5 000-character limit on `body_excerpt` ensures the `ConnectorResult` stays within a single `tiktoken` budget window for embedding.

## Acceptance Criteria

- [ ] `fetch()` returns a `list[ConnectorResult]` with `source_id` matching `confluence:{space}:{id}`
- [ ] `metadata.extra` contains `page_title`, `space_key`, `page_id`
- [ ] `metadata.author` is populated when the API returns a contributor name
- [ ] `strip_confluence_storage()` removes `<ac:structured-macro>` tags and their children
- [ ] `strip_confluence_storage()` returns at most 5 000 characters
- [ ] `fetch()` raises `asyncio.TimeoutError` when total search + mapping exceeds 2 s (mocked)
- [ ] `fetch()` raises `ConnectorAuthError` when called before `authenticate()`

## Dependencies

- TASK-US023-01 (`ConfluenceConnector` skeleton, `_auth_headers()`)
- TASK-US023-02 (`ConfluenceCQLClient.search()`, `ConfluencePageItem`)
- TASK-US021-01 (`ConnectorQuery`, `ConnectorResult`, `ResultMetadata`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests cover plain-text extraction with a real Confluence storage snippet
- [ ] `mypy --strict` passes; no `ruff` lint errors
