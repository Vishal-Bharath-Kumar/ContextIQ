# TASK-US035-01 — API Response Schemas and `TraceDetailService`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US035-01 |
| User Story | US-035 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define the Pydantic API response DTOs for the Replay Explorer — `TraceListItem`, `TraceListResponse`, `TraceDetailResponse` — and implement `TraceDetailService`, which assembles full trace detail by combining the PostgreSQL search index (fast metadata lookup) with the full `ExecutionTrace` JSON fetched from MinIO. Redis is used to cache fetched traces to meet the 2 s AC-5 SLA. These are consumed by the Replay API routes (TASK-US035-02) and drive the Angular components (TASK-US035-03/04).

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `redis.asyncio`, `fakeredis` (tests)

**File locations:**
- `src/audit/replay/schemas.py` — API response DTOs
- `src/audit/replay/service.py` — `TraceDetailService`
- `tests/audit/test_trace_detail_service.py`

---

### API response schemas

```python
# src/audit/replay/schemas.py
from __future__ import annotations
from datetime import datetime
from uuid     import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.audit.trace.schemas import (
    ExecutionTrace, ExecutionPlanStep, RetrievedChunkSummary,
    CompressionDelta, GovernanceDecisionSummary,
)


class TraceListItem(BaseModel):
    """One row in the Replay Explorer search results table (AC-1)."""
    model_config = ConfigDict(frozen=True)

    request_id:         UUID
    user_id:            str
    timestamp:          datetime
    intent:             str
    model_selected:     str | None = None
    governance_blocked: bool       = False
    opa_denied_count:   int        = 0
    object_key:         str        # MinIO pointer — used for detail fetch


class TraceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items:   list[TraceListItem]
    total:   int
    limit:   int
    offset:  int


class TimelineStep(BaseModel):
    """
    One entry in the step-by-step pipeline timeline (AC-2 / AC-3).
    Maps from ExecutionPlanStep with display-friendly fields.
    """
    model_config = ConfigDict(frozen=True)

    step_number: int
    node:        str
    eval_ms:     float | None = None
    metadata:    dict         = Field(default_factory=dict)


class TraceDetailResponse(BaseModel):
    """
    Full trace detail for the detail view (AC-3).
    Fields:
      - intent_classification  → intent (AC-3)
      - retrieved_sources      → chunks with relevance scores (AC-3)
      - compression_delta      → before/after token counts (AC-3)
      - governance_decisions   → allows/denies (AC-3)
      - model_selected         → selected model (AC-3)
      - response_summary       → response summary (AC-3)
      - timeline               → step-by-step pipeline (AC-2)
    """
    model_config = ConfigDict(frozen=True)

    request_id:             UUID
    user_id:                str
    timestamp:              datetime
    latency_ms:             float | None = None

    # AC-3 fields
    intent_classification:  str
    retrieved_sources:      list[RetrievedChunkSummary]
    compression_delta:      CompressionDelta | None     = None
    governance_decisions:   GovernanceDecisionSummary
    model_selected:         str | None                  = None
    prompt_tokens:          int | None                  = None
    completion_tokens:      int | None                  = None
    response_summary:       str | None                  = None

    # AC-2: step-by-step pipeline timeline
    timeline:               list[TimelineStep]

    # Raw trace available for export (AC-6); not serialised in list responses
    _raw_trace:             ExecutionTrace | None = None
```

---

### `TraceDetailService`

```python
# src/audit/replay/service.py
from __future__ import annotations
import json
import logging
from uuid import UUID

import redis.asyncio as aioredis

from src.audit.trace.object_store  import TraceObjectStore, TraceNotFoundError
from src.audit.trace.repository    import TraceIndexRepository, TraceSearchQuery
from src.audit.trace.schemas       import ExecutionTrace, TraceIndexEntry
from src.audit.replay.schemas      import (
    TraceListItem, TraceListResponse, TraceDetailResponse,
    TimelineStep,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_S  = 300   # 5 min; keeps 1-year-old traces within 2 s SLA (AC-5)
_CACHE_PREFIX = "trace:detail:"


class TraceNotFoundInIndexError(Exception):
    pass


class TraceDetailService:
    """
    Assembles Replay Explorer responses by combining:
    - PostgreSQL index (TraceIndexRepository) — fast metadata search
    - MinIO / TraceObjectStore              — full JSON for detail view
    - Redis cache                           — ≤ 2 s SLA for traces up to 1 year old (AC-5)
    """

    def __init__(
        self,
        index_repo:   TraceIndexRepository,
        object_store: TraceObjectStore,
        cache:        aioredis.Redis,
    ) -> None:
        self._index   = index_repo
        self._store   = object_store
        self._cache   = cache

    # ------------------------------------------------------------------ #
    # AC-1 — search                                                        #
    # ------------------------------------------------------------------ #

    async def search(
        self,
        tenant_id: str,
        query:     TraceSearchQuery,
    ) -> TraceListResponse:
        result = await self._index.search(tenant_id, query)
        items  = [_to_list_item(entry) for entry in result.items]
        return TraceListResponse(
            items  = items,
            total  = result.total,
            limit  = result.limit,
            offset = result.offset,
        )

    # ------------------------------------------------------------------ #
    # AC-2, AC-3, AC-5 — detail                                            #
    # ------------------------------------------------------------------ #

    async def get_detail(
        self,
        tenant_id:  str,
        request_id: UUID,
    ) -> TraceDetailResponse:
        """
        Fetch the full trace from cache (Redis) or origin (MinIO).
        Cache hit avoids re-fetching large JSON from object storage (AC-5).
        """
        cache_key = f"{_CACHE_PREFIX}{request_id}"

        # 1. Try cache
        cached = await self._cache.get(cache_key)
        if cached:
            trace = ExecutionTrace.model_validate_json(cached)
            logger.debug("trace.cache_hit request_id=%s", request_id)
            return _to_detail_response(trace)

        # 2. Resolve MinIO pointer from PostgreSQL index
        index_entry = await self._index.get_by_request_id(request_id)
        if index_entry is None:
            raise TraceNotFoundInIndexError(str(request_id))

        # 3. Fetch full trace from MinIO
        trace = await self._store.read(
            object_key = index_entry.object_key,
            version_id = index_entry.object_version or None,
        )

        # 4. Populate cache for subsequent requests (AC-5)
        await self._cache.setex(
            cache_key, _CACHE_TTL_S, trace.model_dump_json()
        )

        return _to_detail_response(trace)

    # ------------------------------------------------------------------ #
    # AC-6 — raw JSON export                                              #
    # ------------------------------------------------------------------ #

    async def get_raw_json(
        self,
        tenant_id:  str,
        request_id: UUID,
    ) -> bytes:
        """Return the full trace JSON as bytes for the download response."""
        cache_key = f"{_CACHE_PREFIX}{request_id}"
        cached    = await self._cache.get(cache_key)
        if cached:
            return cached if isinstance(cached, bytes) else cached.encode()

        index_entry = await self._index.get_by_request_id(request_id)
        if index_entry is None:
            raise TraceNotFoundInIndexError(str(request_id))

        trace = await self._store.read(
            object_key = index_entry.object_key,
            version_id = index_entry.object_version or None,
        )
        payload = trace.model_dump_json(indent=2).encode()
        await self._cache.setex(cache_key, _CACHE_TTL_S, payload)
        return payload


# ------------------------------------------------------------------ #
# Private mapping helpers                                              #
# ------------------------------------------------------------------ #

def _to_list_item(entry: TraceIndexEntry) -> TraceListItem:
    return TraceListItem(
        request_id         = entry.request_id,
        user_id            = entry.user_id,
        timestamp          = entry.timestamp,
        intent             = entry.intent,
        model_selected     = entry.model_selected,
        governance_blocked = entry.governance_blocked,
        opa_denied_count   = entry.opa_denied_count,
        object_key         = entry.object_key,
    )


def _to_detail_response(trace: ExecutionTrace) -> TraceDetailResponse:
    timeline = [
        TimelineStep(
            step_number = i + 1,
            node        = step.node,
            eval_ms     = step.eval_ms,
            metadata    = step.metadata,
        )
        for i, step in enumerate(trace.execution_plan)
    ]
    return TraceDetailResponse(
        request_id           = trace.request_id,
        user_id              = trace.user_id,
        timestamp            = trace.timestamp,
        latency_ms           = trace.latency_ms,
        intent_classification= trace.intent,
        retrieved_sources    = list(trace.retrieved_chunks_post_compression),
        compression_delta    = trace.compression_delta,
        governance_decisions = trace.governance_decisions,
        model_selected       = trace.model_selected,
        prompt_tokens        = trace.prompt_tokens,
        completion_tokens    = trace.completion_tokens,
        response_summary     = trace.response_summary,
        timeline             = timeline,
    )
```

## Acceptance Criteria

- [ ] `TraceDetailResponse` contains all 6 AC-3 display fields: `intent_classification`, `retrieved_sources` (with relevance scores), `compression_delta`, `governance_decisions`, `model_selected`, `response_summary`
- [ ] `TraceDetailService.get_detail()` checks Redis cache before fetching from MinIO (AC-5)
- [ ] Cache is populated with a 5-minute TTL after a MinIO fetch
- [ ] `TraceDetailService.get_raw_json()` returns UTF-8 JSON bytes (AC-6)
- [ ] `TraceDetailService.search()` delegates to `TraceIndexRepository.search()` — no direct SQL in the service
- [ ] `TraceNotFoundInIndexError` is raised (not a generic exception) when `request_id` is not in the PostgreSQL index

## Dependencies

- TASK-US034-01 (`ExecutionTrace`, sub-schemas)
- TASK-US034-02 (`TraceObjectStore`)
- TASK-US034-03 (`TraceIndexRepository`, `TraceSearchQuery`, `TraceIndexEntry`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
