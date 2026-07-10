# TASK-US023-04 — `ConfluencePageChunker` and `ConfluenceConnector.sync()`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US023-04 |
| User Story | US-023 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ConfluencePageChunker` — which splits pages exceeding 10 000 tokens at natural section boundaries (headings) — and `ConfluenceConnector.sync()` — which fetches only pages updated since `last_sync_at` using a CQL `lastModified` filter, writes chunks to the sync event, and persists the sync cursor. Satisfies US-023 AC-5 and AC-6.

## Implementation Details

**Technology:** Python 3.11+, `tiktoken`, `re`, SQLAlchemy 2.x async, `aiokafka`

**File locations:**
- `src/connectors/confluence/chunker.py` — `ConfluencePageChunker`, `PageChunk`
- `src/connectors/confluence/connector.py` — `ConfluenceConnector.sync()` (extend existing class)
- `tests/connectors/confluence/test_confluence_chunker.py`
- `tests/connectors/confluence/test_confluence_sync.py`

**`PageChunk` and `ConfluencePageChunker`:**

```python
# src/connectors/confluence/chunker.py
from pydantic import BaseModel, ConfigDict
import re, tiktoken

TOKEN_CHUNK_THRESHOLD = 10_000   # US-023 AC-6: pages above this are chunked

# Heading patterns in plain text produced by strip_confluence_storage()
_HEADING_RE = re.compile(r'\n(?=#{1,3} |\n[A-Z][^\n]{3,80}\n[=-]{3,})')

_ENCODER = tiktoken.get_encoding("cl100k_base")   # module-level singleton

class PageChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_id:      str
    chunk_index:  int           # 0-based ordinal within the page
    content:      str
    token_count:  int
    heading:      str | None    # first heading in this chunk, if detected


class ConfluencePageChunker:
    """
    Splits a Confluence page into token-bounded chunks at natural section boundaries.
    Pages under TOKEN_CHUNK_THRESHOLD are returned as a single chunk.
    """

    def chunk(self, page_id: str, plain_text: str) -> list[PageChunk]:
        tokens = _ENCODER.encode(plain_text)
        if len(tokens) <= TOKEN_CHUNK_THRESHOLD:
            return [PageChunk(
                page_id     = page_id,
                chunk_index = 0,
                content     = plain_text,
                token_count = len(tokens),
                heading     = self._extract_heading(plain_text),
            )]

        return self._split_at_headings(page_id, plain_text)

    def _split_at_headings(self, page_id: str, text: str) -> list[PageChunk]:
        """
        Split at heading boundaries; merge short sections to keep
        chunks close to but not exceeding TOKEN_CHUNK_THRESHOLD.
        """
        sections = _HEADING_RE.split(text)
        chunks: list[PageChunk] = []
        buffer = ""

        for section in sections:
            candidate = (buffer + "\n" + section).strip() if buffer else section.strip()
            if len(_ENCODER.encode(candidate)) > TOKEN_CHUNK_THRESHOLD:
                if buffer:
                    chunks.append(self._make_chunk(page_id, len(chunks), buffer))
                # Hard-split oversized section at token boundary
                for hard_chunk in self._hard_split(page_id, len(chunks), section):
                    chunks.append(hard_chunk)
                buffer = ""
            else:
                buffer = candidate

        if buffer:
            chunks.append(self._make_chunk(page_id, len(chunks), buffer))

        return chunks or [PageChunk(page_id=page_id, chunk_index=0, content=text[:5000],
                                    token_count=len(_ENCODER.encode(text[:5000])), heading=None)]

    def _hard_split(self, page_id: str, base_index: int, text: str) -> list[PageChunk]:
        """Token-boundary split for oversized sections with no heading markers."""
        tokens  = _ENCODER.encode(text)
        chunks  = []
        for i in range(0, len(tokens), TOKEN_CHUNK_THRESHOLD):
            slice_tokens = tokens[i:i + TOKEN_CHUNK_THRESHOLD]
            content      = _ENCODER.decode(slice_tokens)
            chunks.append(self._make_chunk(page_id, base_index + len(chunks), content))
        return chunks

    def _make_chunk(self, page_id: str, index: int, content: str) -> PageChunk:
        return PageChunk(
            page_id     = page_id,
            chunk_index = index,
            content     = content,
            token_count = len(_ENCODER.encode(content)),
            heading     = self._extract_heading(content),
        )

    @staticmethod
    def _extract_heading(text: str) -> str | None:
        m = re.search(r'^#{1,3} (.+)$', text, re.MULTILINE)
        return m.group(1).strip() if m else None
```

**`ConfluenceConnector.sync()`:**

```python
# src/connectors/confluence/connector.py  — extend existing class
from datetime import datetime, timezone, timedelta
from src.connector_sdk.schemas.sync     import SyncResult
from src.connectors.confluence.cql_client  import ConfluenceCQLClient
from src.connectors.confluence.chunker     import ConfluencePageChunker
from src.connectors.confluence.html_stripper import strip_confluence_storage
from src.connectors.github.sync_store      import ConnectorSyncStore  # reused from US-022

    async def sync(self) -> SyncResult:
        sync_store = ConnectorSyncStore(self._session)
        cql_client = ConfluenceCQLClient(self._config)
        chunker    = ConfluencePageChunker()
        now        = datetime.now(tz=timezone.utc)

        last_sync  = await sync_store.get_last_sync_at("confluence")
        if last_sync is None:
            last_sync = now - timedelta(days=self._config.default_days)

        # CQL lastModified filter (ISO-8601 date without time for CQL compatibility)
        since_date  = last_sync.strftime("%Y-%m-%d")
        extra_cql   = f'lastModified >= "{since_date}"'

        items_processed = 0
        items_failed    = 0
        errors: list[str] = []

        try:
            pages = await cql_client.search(
                query        = "",          # empty query = all pages in spaces matching filter
                spaces       = self._config.spaces,
                auth_headers = self._auth_headers(),
                max_results  = 500,
                extra_cql    = extra_cql,
            )
        except Exception as exc:
            errors.append(f"CQL sync search failed: {type(exc).__name__}: {exc}")
            return SyncResult(
                items_processed = 0,
                items_failed    = 1,
                last_sync_at    = now,
                errors          = errors,
            )

        for page in pages:
            try:
                plain = strip_confluence_storage(page.body_excerpt)
                chunks = chunker.chunk(page.page_id, plain)
                items_processed += len(chunks)
            except Exception as exc:
                items_failed += 1
                errors.append(f"{page.page_id}: {type(exc).__name__}: {exc}")

        await sync_store.set_last_sync_at("confluence", now)
        await self._emit_sync_event(items_processed=items_processed, synced_at=now)
        return SyncResult(
            items_processed = items_processed,
            items_failed    = items_failed,
            last_sync_at    = now,
            errors          = errors,
        )

    async def _emit_sync_event(self, items_processed: int, synced_at: datetime) -> None:
        import json
        from src.events.producer import get_kafka_producer
        event = {
            "event_type":      "source_sync_completed",
            "connector_id":    "confluence",
            "items_processed": items_processed,
            "synced_at":       synced_at.isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait("contextiq.source.sync", value=json.dumps(event).encode())
```

**CQL `lastModified` filter behaviour:**

The CQL `lastModified >= "YYYY-MM-DD"` clause filters to pages updated on or after the given date. Date granularity (day, not second) is intentional — Confluence CQL does not support sub-day precision for `lastModified`. The last few hours of pages from the prior sync day may be re-fetched; EP-008 deduplicates on `source_id`.

## Acceptance Criteria

- [ ] `ConfluencePageChunker.chunk()` returns a single `PageChunk` when the page is ≤ 10 000 tokens
- [ ] `ConfluencePageChunker.chunk()` returns multiple chunks when the page exceeds 10 000 tokens
- [ ] Each chunk has `token_count ≤ TOKEN_CHUNK_THRESHOLD`
- [ ] `chunk_index` is 0-based and sequential across all returned chunks
- [ ] `sync()` uses `lastModified >= "{last_sync_date}"` in the CQL query
- [ ] `sync()` defaults to `now - default_days` when no prior sync cursor exists
- [ ] `sync()` writes the updated cursor to `connector_sync_state` after completion
- [ ] `sync()` emits a `source_sync_completed` event to `contextiq.source.sync` Kafka topic

## Dependencies

- TASK-US023-01 (`ConfluenceConnector`, `_auth_headers()`)
- TASK-US023-02 (`ConfluenceCQLClient.search()`)
- TASK-US023-03 (`strip_confluence_storage()`)
- TASK-US021-01 (`SyncResult`)
- TASK-US022-04 (`ConnectorSyncStore` — reused directly from GitHub connector)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Chunker tests verify heading-boundary splits and hard-splits for headingless long sections
- [ ] Sync tests mock `ConnectorSyncStore`, `ConfluenceCQLClient`, and Kafka producer
- [ ] `mypy --strict` passes; no `ruff` lint errors
