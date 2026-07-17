"""Tests for TraceDetailService — TASK-US035-01.

Uses:
  - fakeredis[aioredis] — async in-memory Redis (no server required)
  - AsyncMock           — stubs for TraceIndexRepository and TraceObjectStore
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
import pytest_asyncio

from src.audit.replay.schemas import (
    TraceDetailResponse,
    TraceListResponse,
)
from src.audit.replay.service import (
    _CACHE_PREFIX,
    _CACHE_TTL_S,
    TraceDetailService,
    TraceNotFoundInIndexError,
)
from src.audit.trace.repository import TraceSearchQuery, TraceSearchResult
from src.audit.trace.schemas import (
    CompressionDelta,
    ExecutionPlanStep,
    ExecutionTrace,
    GovernanceDecisionSummary,
    RetrievedChunkSummary,
    TraceIndexEntry,
)

# ------------------------------------------------------------------ #
# Constants                                                            #
# ------------------------------------------------------------------ #

_REQUEST_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_TENANT_ID = "tenant-test"
_BASE_TS = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)

# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def _make_trace(
    *,
    request_id: uuid.UUID = _REQUEST_ID,
    intent: str = "technical_support",
    execution_plan: list[ExecutionPlanStep] | None = None,
) -> ExecutionTrace:
    return ExecutionTrace(
        request_id=request_id,
        tenant_id=_TENANT_ID,
        user_id="user-1",
        timestamp=_BASE_TS,
        prompt="How do I reset my password?",
        intent=intent,
        latency_ms=123.4,
        execution_plan=execution_plan or [
            ExecutionPlanStep(node="retrieval_node", eval_ms=50.0),
            ExecutionPlanStep(node="compression_node", eval_ms=30.0),
        ],
        retrieved_chunks_post_compression=[
            RetrievedChunkSummary(
                chunk_id="chunk-1",
                source_id="src-1",
                relevance_score=0.95,
            )
        ],
        compression_delta=CompressionDelta(
            tokens_before=500,
            tokens_after=300,
            chunks_before=5,
            chunks_after=3,
        ),
        governance_decisions=GovernanceDecisionSummary(
            findings_count=1,
            opa_denied_count=0,
            governance_blocked=False,
        ),
        model_selected="gpt-4o",
        prompt_tokens=300,
        completion_tokens=150,
        response_summary="Your password can be reset via the account settings page.",
        object_key=f"traces/{_TENANT_ID}/2025/06/{_REQUEST_ID}.json",
        object_version="v1",
    )


def _make_index_entry(
    trace: ExecutionTrace,
) -> TraceIndexEntry:
    return TraceIndexEntry(
        request_id=trace.request_id,
        tenant_id=trace.tenant_id,
        user_id=trace.user_id,
        timestamp=trace.timestamp,
        intent=trace.intent,
        model_selected=trace.model_selected,
        governance_blocked=trace.governance_decisions.governance_blocked,
        opa_denied_count=trace.governance_decisions.opa_denied_count,
        object_key=trace.object_key or "",
        object_version=trace.object_version,
    )


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest_asyncio.fixture
async def fake_cache() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
    """Per-test in-memory async Redis."""
    cache = fakeredis.aioredis.FakeRedis()
    yield cache
    await cache.aclose()


@pytest.fixture
def mock_index() -> MagicMock:
    mock = MagicMock()
    mock.search = AsyncMock()
    mock.get_by_request_id = AsyncMock()
    return mock


@pytest.fixture
def mock_store() -> MagicMock:
    mock = MagicMock()
    mock.read = AsyncMock()
    return mock


@pytest.fixture
def service(
    mock_index: MagicMock,
    mock_store: MagicMock,
    fake_cache: fakeredis.aioredis.FakeRedis,
) -> TraceDetailService:
    return TraceDetailService(
        index_repo=mock_index,
        object_store=mock_store,
        cache=fake_cache,
    )


# ------------------------------------------------------------------ #
# search — AC-1                                                        #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_delegates_to_index_repository(
    service: TraceDetailService,
    mock_index: AsyncMock,
) -> None:
    trace = _make_trace()
    entry = _make_index_entry(trace)
    mock_index.search.return_value = TraceSearchResult(
        items=[entry],
        total=1,
        limit=50,
        offset=0,
    )
    query = TraceSearchQuery(user_id="user-1")

    result = await service.search(_TENANT_ID, query)

    mock_index.search.assert_awaited_once_with(_TENANT_ID, query)
    assert isinstance(result, TraceListResponse)
    assert result.total == 1
    assert result.items[0].request_id == trace.request_id
    assert result.items[0].intent == trace.intent
    assert result.items[0].object_key == trace.object_key


@pytest.mark.asyncio
async def test_search_returns_empty_list(
    service: TraceDetailService,
    mock_index: AsyncMock,
) -> None:
    mock_index.search.return_value = TraceSearchResult(
        items=[], total=0, limit=50, offset=0
    )
    result = await service.search(_TENANT_ID, TraceSearchQuery())

    assert result.items == []
    assert result.total == 0


# ------------------------------------------------------------------ #
# get_detail — cache miss → MinIO fetch → cache populate (AC-5)       #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_detail_cache_miss_fetches_from_minio(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
    fake_cache: fakeredis.aioredis.FakeRedis,
) -> None:
    trace = _make_trace()
    entry = _make_index_entry(trace)
    mock_index.get_by_request_id.return_value = entry
    mock_store.read.return_value = trace

    result = await service.get_detail(_TENANT_ID, _REQUEST_ID)

    mock_index.get_by_request_id.assert_awaited_once_with(_REQUEST_ID)
    mock_store.read.assert_awaited_once_with(
        object_key=entry.object_key,
        version_id=entry.object_version,
    )
    assert isinstance(result, TraceDetailResponse)
    assert result.request_id == trace.request_id
    assert result.intent_classification == trace.intent

    # cache must be populated
    cached = await fake_cache.get(f"{_CACHE_PREFIX}{_REQUEST_ID}")
    assert cached is not None


@pytest.mark.asyncio
async def test_get_detail_cache_miss_sets_ttl(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
    fake_cache: fakeredis.aioredis.FakeRedis,
) -> None:
    trace = _make_trace()
    mock_index.get_by_request_id.return_value = _make_index_entry(trace)
    mock_store.read.return_value = trace

    await service.get_detail(_TENANT_ID, _REQUEST_ID)

    ttl = await fake_cache.ttl(f"{_CACHE_PREFIX}{_REQUEST_ID}")
    assert 0 < ttl <= _CACHE_TTL_S


# ------------------------------------------------------------------ #
# get_detail — cache hit (AC-5)                                        #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_detail_cache_hit_skips_minio(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
    fake_cache: fakeredis.aioredis.FakeRedis,
) -> None:
    trace = _make_trace()
    cache_key = f"{_CACHE_PREFIX}{_REQUEST_ID}"
    await fake_cache.setex(cache_key, _CACHE_TTL_S, trace.model_dump_json())

    result = await service.get_detail(_TENANT_ID, _REQUEST_ID)

    mock_index.get_by_request_id.assert_not_called()
    mock_store.read.assert_not_called()
    assert result.request_id == trace.request_id


# ------------------------------------------------------------------ #
# get_detail — AC-5: cache-hit < 2 s SLA                              #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_detail_cache_hit_completes_within_2s(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
    fake_cache: fakeredis.aioredis.FakeRedis,
) -> None:
    """AC-5: cache-hit detail fetch completes in under 2 s (no live MinIO)."""
    trace = _make_trace()
    cache_key = f"{_CACHE_PREFIX}{_REQUEST_ID}"
    await fake_cache.setex(cache_key, _CACHE_TTL_S, trace.model_dump_json())

    start = time.monotonic()
    result = await service.get_detail(_TENANT_ID, _REQUEST_ID)
    elapsed_ms = (time.monotonic() - start) * 1000

    assert result is not None
    assert result.request_id == trace.request_id
    assert elapsed_ms < 2000, f"Cache-hit detail took {elapsed_ms:.0f} ms (limit 2000 ms)"
    mock_store.read.assert_not_called()


# ------------------------------------------------------------------ #
# get_detail — not found in index                                      #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_detail_raises_trace_not_found_in_index_error(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    mock_index.get_by_request_id.return_value = None

    with pytest.raises(TraceNotFoundInIndexError, match=str(_REQUEST_ID)):
        await service.get_detail(_TENANT_ID, _REQUEST_ID)

    mock_store.read.assert_not_awaited()


# ------------------------------------------------------------------ #
# get_detail — AC-3 display fields                                     #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_detail_response_contains_all_ac3_fields(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    trace = _make_trace()
    mock_index.get_by_request_id.return_value = _make_index_entry(trace)
    mock_store.read.return_value = trace

    result = await service.get_detail(_TENANT_ID, _REQUEST_ID)

    assert result.intent_classification == trace.intent
    assert len(result.retrieved_sources) == 1
    assert result.retrieved_sources[0].relevance_score == 0.95
    assert result.compression_delta is not None
    assert result.compression_delta.tokens_before == 500
    assert result.governance_decisions.governance_blocked is False
    assert result.model_selected == "gpt-4o"
    assert result.response_summary is not None
    assert "password" in result.response_summary


@pytest.mark.asyncio
async def test_get_detail_timeline_maps_execution_plan(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    trace = _make_trace(
        execution_plan=[
            ExecutionPlanStep(node="retrieval_node", eval_ms=50.0, metadata={"k": "v"}),
            ExecutionPlanStep(node="compression_node", eval_ms=30.0),
        ]
    )
    mock_index.get_by_request_id.return_value = _make_index_entry(trace)
    mock_store.read.return_value = trace

    result = await service.get_detail(_TENANT_ID, _REQUEST_ID)

    assert len(result.timeline) == 2
    assert result.timeline[0].step_number == 1
    assert result.timeline[0].node == "retrieval_node"
    assert result.timeline[0].eval_ms == 50.0
    assert result.timeline[0].metadata == {"k": "v"}
    assert result.timeline[1].step_number == 2
    assert result.timeline[1].node == "compression_node"


# ------------------------------------------------------------------ #
# get_raw_json — AC-6                                                  #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_raw_json_returns_utf8_bytes(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    trace = _make_trace()
    mock_index.get_by_request_id.return_value = _make_index_entry(trace)
    mock_store.read.return_value = trace

    raw = await service.get_raw_json(_TENANT_ID, _REQUEST_ID)

    assert isinstance(raw, bytes)
    parsed = json.loads(raw.decode("utf-8"))
    assert str(parsed["request_id"]) == str(_REQUEST_ID)


@pytest.mark.asyncio
async def test_get_raw_json_cache_hit_skips_minio(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
    fake_cache: fakeredis.aioredis.FakeRedis,
) -> None:
    trace = _make_trace()
    cache_key = f"{_CACHE_PREFIX}{_REQUEST_ID}"
    payload = trace.model_dump_json(indent=2).encode()
    await fake_cache.setex(cache_key, _CACHE_TTL_S, payload)

    raw = await service.get_raw_json(_TENANT_ID, _REQUEST_ID)

    mock_store.read.assert_not_awaited()
    assert raw == payload


@pytest.mark.asyncio
async def test_get_raw_json_raises_when_not_in_index(
    service: TraceDetailService,
    mock_index: AsyncMock,
) -> None:
    mock_index.get_by_request_id.return_value = None

    with pytest.raises(TraceNotFoundInIndexError):
        await service.get_raw_json(_TENANT_ID, _REQUEST_ID)


@pytest.mark.asyncio
async def test_get_raw_json_populates_cache(
    service: TraceDetailService,
    mock_index: AsyncMock,
    mock_store: AsyncMock,
    fake_cache: fakeredis.aioredis.FakeRedis,
) -> None:
    trace = _make_trace()
    mock_index.get_by_request_id.return_value = _make_index_entry(trace)
    mock_store.read.return_value = trace

    await service.get_raw_json(_TENANT_ID, _REQUEST_ID)

    cached = await fake_cache.get(f"{_CACHE_PREFIX}{_REQUEST_ID}")
    assert cached is not None
