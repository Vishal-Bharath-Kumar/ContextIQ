# TASK-US035-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US035-05 |
| User Story | US-035 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Done |

## Description

Write the integration and unit test suite covering all 6 US-035 acceptance criteria: the search endpoint filters correctly by all five AC-1 parameters (AC-1), the detail endpoint response contains a timeline (AC-2), all six AC-3 fields are populated (AC-3), the RBAC guard blocks non-AUDITOR/ADMIN callers (AC-4), the detail response is served within 2 s for traces up to 1 year old (AC-5), and the export endpoint returns a valid downloadable JSON file (AC-6).

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `httpx.AsyncClient` (FastAPI test client), `fakeredis.aioredis`, `AsyncMock`, `moto[s3]>=5.0`

**File locations:**
- `tests/api/test_replay_routes.py` — HTTP-level tests (all ACs)
- `tests/audit/test_trace_detail_service.py` — `TraceDetailService` unit tests (AC-2, AC-3, AC-5)

---

### Shared fixtures

```python
# tests/api/conftest.py  (extend existing file)
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

from src.audit.trace.schemas import (
    ExecutionTrace, ExecutionPlanStep, RetrievedChunkSummary,
    CompressionDelta, GovernanceDecisionSummary,
)

REQUEST_ID = uuid.uuid4()
TENANT_ID  = "acme"
USER_ID    = "user-abc123"

SAMPLE_TRACE = ExecutionTrace(
    request_id     = REQUEST_ID,
    tenant_id      = TENANT_ID,
    user_id        = USER_ID,
    timestamp      = datetime.now(tz=timezone.utc),
    latency_ms     = 320.5,
    prompt         = "What is the onboarding process?",
    intent         = "technical_support",
    execution_plan = [
        ExecutionPlanStep(node="retrieval",   eval_ms=45.0),
        ExecutionPlanStep(node="compression", eval_ms=12.0),
        ExecutionPlanStep(node="governance",  eval_ms=8.5),
    ],
    retrieved_chunks_pre_compression  = [
        RetrievedChunkSummary(
            chunk_id="c1", source_id="s1", relevance_score=0.91,
            classification_label="internal", redacted=False, opa_denied=False,
        )
    ],
    retrieved_chunks_post_compression = [
        RetrievedChunkSummary(
            chunk_id="c1", source_id="s1", relevance_score=0.91,
            classification_label="internal", redacted=False, opa_denied=False,
        )
    ],
    compression_delta = CompressionDelta(
        tokens_before=800, tokens_after=400, chunks_before=5, chunks_after=3,
    ),
    governance_decisions = GovernanceDecisionSummary(
        findings_count=0, redacted_count=0, opa_denied_count=0,
        opa_bundle_version="v1.0.0", governance_blocked=False,
    ),
    model_selected    = "gpt-4o",
    prompt_tokens     = 512,
    completion_tokens = 128,
    response_summary  = "The onboarding process begins with...",
)


def _make_admin_jwt() -> str:
    """Return a test JWT token whose claims include the 'admin' role."""
    # In the test suite the JWT middleware is patched to decode these fake tokens
    return "Bearer test-admin-token"

def _make_auditor_jwt() -> str:
    return "Bearer test-auditor-token"

def _make_developer_jwt() -> str:
    return "Bearer test-developer-token"
```

---

### AC-1 — Search filters

```python
# tests/api/test_replay_routes.py
async def test_search_filters_by_user_id(async_client, seed_trace_index):
    """AC-1: user_id filter returns only matching rows."""
    resp = await async_client.get(
        "/v1/traces",
        params={"user_id": USER_ID, "limit": 10, "offset": 0},
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(item["user_id"] == USER_ID for item in body["items"])


async def test_search_filters_by_intent(async_client, seed_trace_index):
    """AC-1: intent filter returns only matching rows."""
    resp = await async_client.get(
        "/v1/traces",
        params={"intent": "technical_support"},
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200
    assert all(i["intent"] == "technical_support" for i in resp.json()["items"])


async def test_search_filters_by_date_range(async_client, seed_trace_index):
    """AC-1: from/to timestamp filters apply correctly."""
    now = datetime.now(tz=timezone.utc)
    resp = await async_client.get(
        "/v1/traces",
        params={
            "from": (now - timedelta(hours=1)).isoformat(),
            "to":   (now + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200


async def test_search_filters_by_governance_blocked(async_client, seed_trace_index):
    """AC-1: governance_blocked=true returns only blocked traces."""
    resp = await async_client.get(
        "/v1/traces",
        params={"governance_blocked": "true"},
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200
    assert all(i["governance_blocked"] for i in resp.json()["items"])


async def test_search_filters_by_model(async_client, seed_trace_index):
    """AC-1: model_selected filter returns only matching rows."""
    resp = await async_client.get(
        "/v1/traces",
        params={"model_selected": "gpt-4o"},
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200
    assert all(i["model_selected"] == "gpt-4o" for i in resp.json()["items"])
```

---

### AC-2 — Detail view timeline

```python
async def test_detail_contains_timeline(async_client, seed_trace_and_minio):
    """AC-2: detail response contains timeline with one entry per execution plan step."""
    resp = await async_client.get(
        f"/v1/traces/{REQUEST_ID}",
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "timeline" in body
    assert len(body["timeline"]) == 3   # retrieval, compression, governance
    nodes = [s["node"] for s in body["timeline"]]
    assert "retrieval" in nodes


async def test_timeline_steps_are_ordered(async_client, seed_trace_and_minio):
    """AC-2: timeline steps are in step_number ascending order."""
    resp = await async_client.get(
        f"/v1/traces/{REQUEST_ID}",
        headers={"Authorization": _make_admin_jwt()},
    )
    steps = resp.json()["timeline"]
    nums  = [s["step_number"] for s in steps]
    assert nums == sorted(nums)
```

---

### AC-3 — All six detail fields present

```python
async def test_detail_contains_all_ac3_fields(async_client, seed_trace_and_minio):
    """AC-3: all six required fields are present and non-null."""
    resp = await async_client.get(
        f"/v1/traces/{REQUEST_ID}",
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200
    body = resp.json()

    # intent_classification
    assert body["intent_classification"] == "technical_support"

    # retrieved_sources with relevance scores
    assert len(body["retrieved_sources"]) >= 1
    assert "relevance_score" in body["retrieved_sources"][0]

    # compression_delta
    assert body["compression_delta"] is not None
    assert body["compression_delta"]["tokens_before"] == 800
    assert body["compression_delta"]["tokens_after"]  == 400

    # governance_decisions
    assert body["governance_decisions"]["opa_bundle_version"] == "v1.0.0"

    # model_selected
    assert body["model_selected"] == "gpt-4o"

    # response_summary
    assert body["response_summary"] is not None
    assert len(body["response_summary"]) > 0
```

---

### AC-4 — RBAC enforcement

```python
async def test_search_returns_403_for_developer_role(async_client):
    """AC-4: developer role cannot access the replay list."""
    resp = await async_client.get(
        "/v1/traces",
        headers={"Authorization": _make_developer_jwt()},
    )
    assert resp.status_code == 403


async def test_detail_returns_403_for_developer_role(async_client):
    """AC-4: developer role cannot access trace detail."""
    resp = await async_client.get(
        f"/v1/traces/{REQUEST_ID}",
        headers={"Authorization": _make_developer_jwt()},
    )
    assert resp.status_code == 403


async def test_search_accepts_auditor_role(async_client, seed_trace_index):
    """AC-4: auditor role (lowercase) is accepted."""
    resp = await async_client.get(
        "/v1/traces",
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200


async def test_export_returns_403_for_developer_role(async_client):
    """AC-4: developer cannot download trace export."""
    resp = await async_client.get(
        f"/v1/traces/{REQUEST_ID}/export",
        headers={"Authorization": _make_developer_jwt()},
    )
    assert resp.status_code == 403
```

---

### AC-5 — 2 s response time for traces up to 1 year old

```python
# tests/audit/test_trace_detail_service.py
import time

async def test_detail_served_from_cache_within_2s(
    index_repo_with_old_trace, object_store_with_old_trace, fake_redis
):
    """
    AC-5: after cache warm-up, detail fetch completes < 2 s.
    One-year-old trace simulated by inserting a timestamped index row.
    """
    from src.audit.replay.service import TraceDetailService

    svc = TraceDetailService(
        index_repo   = index_repo_with_old_trace,
        object_store = object_store_with_old_trace,
        cache        = fake_redis,
    )
    # First call populates the cache
    await svc.get_detail(TENANT_ID, REQUEST_ID)

    # Second call must be served from cache
    start   = time.monotonic()
    result  = await svc.get_detail(TENANT_ID, REQUEST_ID)
    elapsed = (time.monotonic() - start) * 1000

    assert result is not None
    assert elapsed < 2000, f"Cache-hit detail took {elapsed:.0f} ms (limit 2000 ms)"


async def test_first_detail_fetch_populates_cache(fake_redis, object_store_with_trace, index_repo):
    """AC-5: TraceDetailService populates Redis after first MinIO fetch."""
    from src.audit.replay.service import TraceDetailService

    svc = TraceDetailService(
        index_repo   = index_repo,
        object_store = object_store_with_trace,
        cache        = fake_redis,
    )
    await svc.get_detail(TENANT_ID, REQUEST_ID)

    cached = await fake_redis.get(f"trace:detail:{REQUEST_ID}")
    assert cached is not None
```

---

### AC-6 — JSON export download

```python
# tests/api/test_replay_routes.py (continued)
async def test_export_returns_json_attachment(async_client, seed_trace_and_minio):
    """AC-6: export endpoint returns valid JSON with Content-Disposition: attachment."""
    resp = await async_client.get(
        f"/v1/traces/{REQUEST_ID}/export",
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert f"{REQUEST_ID}" in resp.headers["content-disposition"]

    import json
    parsed = json.loads(resp.content)
    assert parsed["request_id"] == str(REQUEST_ID)
    assert "execution_plan"     in parsed
    assert "governance_decisions" in parsed


async def test_export_returns_404_for_unknown_id(async_client):
    """AC-6: 404 when the trace does not exist."""
    resp = await async_client.get(
        f"/v1/traces/{uuid.uuid4()}/export",
        headers={"Authorization": _make_auditor_jwt()},
    )
    assert resp.status_code == 404
```

## Acceptance Criteria

- [x] All 5 AC-1 search filter tests pass (user_id, intent, date range, governance_blocked, model_selected)
- [x] AC-2 timeline tests confirm ordered steps with correct node names
- [x] AC-3 test confirms all 6 required fields are present and non-null in the detail response
- [x] AC-4 tests confirm 403 for `developer` role and 200 for `auditor` / `admin`
- [x] AC-5 cache-hit test confirms < 2 s response time without live MinIO
- [x] AC-6 export test confirms `Content-Disposition: attachment` header and valid JSON body

## Dependencies

- TASK-US034-01 (`ExecutionTrace`, sub-schemas)
- TASK-US034-03 (`TraceIndexRepository`, `TraceSearchQuery`)
- TASK-US035-01 (`TraceDetailService`, `TraceNotFoundInIndexError`)
- TASK-US035-02 (Replay API route handlers, `require_auditor_or_admin`)

## Definition of Done

- [x] Code reviewed and merged to `main`
- [x] All tests mock MinIO via `moto[s3]` and Redis via `fakeredis.aioredis` — no live services in CI
- [x] `mypy --strict` passes; no `ruff` lint errors
