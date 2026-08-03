"""TraceDetailService — assembles Replay Explorer responses — TASK-US035-01.

Combines:
  - PostgreSQL index (TraceIndexRepository) — fast metadata search
  - MinIO / TraceObjectStore              — full JSON for detail view
  - Redis cache                           — ≤ 2 s SLA for traces up to 1 year old (AC-5)
"""
from __future__ import annotations

import logging
from uuid import UUID

import redis.asyncio as aioredis

from src.audit.replay.schemas import (
    TimelineStep,
    TraceDetailResponse,
    TraceListItem,
    TraceListResponse,
)
from src.audit.trace.object_store import TraceObjectStore
from src.audit.trace.repository import TraceIndexRepository, TraceSearchQuery
from src.audit.trace.schemas import ExecutionTrace

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 300  # 5 min; keeps 1-year-old traces within 2 s SLA (AC-5)
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
        index_repo: TraceIndexRepository,
        object_store: TraceObjectStore,
        cache: aioredis.Redis,
    ) -> None:
        self._index = index_repo
        self._store = object_store
        self._cache = cache

    # ------------------------------------------------------------------ #
    # AC-1 — search                                                        #
    # ------------------------------------------------------------------ #

    async def search(
        self,
        tenant_id: str,
        query: TraceSearchQuery,
    ) -> TraceListResponse:
        result = await self._index.search(tenant_id, query)
        items = [_to_list_item(entry) for entry in result.items]
        return TraceListResponse(
            items=items,
            total=result.total,
            limit=result.limit,
            offset=result.offset,
        )

    # ------------------------------------------------------------------ #
    # AC-2, AC-3, AC-5 — detail                                            #
    # ------------------------------------------------------------------ #

    async def get_detail(
        self,
        tenant_id: str,
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
            object_key=index_entry.object_key,
            version_id=index_entry.object_version or None,
        )

        # 4. Populate cache for subsequent requests (AC-5)
        await self._cache.setex(
            cache_key, _CACHE_TTL_S, trace.model_dump_json()
        )

        return _to_detail_response(trace)

    # ------------------------------------------------------------------ #
    # AC-6 — raw JSON export                                               #
    # ------------------------------------------------------------------ #

    async def get_raw_json(
        self,
        tenant_id: str,
        request_id: UUID,
    ) -> bytes:
        """Return the full trace JSON as bytes for the download response."""
        cache_key = f"{_CACHE_PREFIX}{request_id}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached if isinstance(cached, bytes) else cached.encode()

        index_entry = await self._index.get_by_request_id(request_id)
        if index_entry is None:
            raise TraceNotFoundInIndexError(str(request_id))

        trace = await self._store.read(
            object_key=index_entry.object_key,
            version_id=index_entry.object_version or None,
        )
        payload = trace.model_dump_json(indent=2).encode()
        await self._cache.setex(cache_key, _CACHE_TTL_S, payload)
        return payload


# ------------------------------------------------------------------ #
# Private mapping helpers                                              #
# ------------------------------------------------------------------ #

def _to_list_item(entry: object) -> TraceListItem:
    return TraceListItem(
        request_id=entry.request_id,
        user_id=entry.user_id,
        timestamp=entry.timestamp,
        intent=entry.intent,
        model_selected=entry.model_selected,
        governance_blocked=entry.governance_blocked,
        opa_denied_count=entry.opa_denied_count,
        object_key=entry.object_key,
    )


def _to_detail_response(trace: ExecutionTrace) -> TraceDetailResponse:
    timeline = [
        TimelineStep(
            step_number=i + 1,
            node=step.node,
            eval_ms=step.eval_ms,
            metadata=step.metadata,
        )
        for i, step in enumerate(trace.execution_plan)
    ]
    return TraceDetailResponse(
        request_id=trace.request_id,
        user_id=trace.user_id,
        timestamp=trace.timestamp,
        latency_ms=trace.latency_ms,
        intent_classification=trace.intent,
        retrieved_sources=list(trace.retrieved_chunks_post_compression),
        compression_delta=trace.compression_delta,
        governance_decisions=trace.governance_decisions,
        model_selected=trace.model_selected,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        response_summary=trace.response_summary,
        timeline=timeline,
    )
