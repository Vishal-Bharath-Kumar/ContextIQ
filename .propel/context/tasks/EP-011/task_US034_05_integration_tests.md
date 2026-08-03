# TASK-US034-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US034-05 |
| User Story | US-034 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Done |

## Description

Write the integration and unit test suite covering all 6 US-034 acceptance criteria: MinIO write produces an immutable JSON object (AC-1), all 10 required trace fields present (AC-2), write-once versioning creates a new version instead of overwriting (AC-3), PostgreSQL search index correct by all four search columns (AC-4), retention policy enforced at a 90-day floor (AC-5), and trace writes do not add latency to the main request path (AC-6).

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `moto[s3]>=5.0` for MinIO/S3 mock, `AsyncMock`, `unittest.mock`

**File locations:**
- `tests/audit/test_trace_object_store.py` — AC-1, AC-3, AC-5
- `tests/audit/test_trace_index_repository.py` — AC-4
- `tests/audit/test_trace_writer_node.py` — AC-2, AC-6
- `tests/audit/conftest.py` — shared fixtures

---

### Shared fixtures

```python
# tests/audit/conftest.py
import pytest
import uuid
from datetime import datetime, timezone

REQUEST_ID = uuid.uuid4()
TENANT_ID  = "acme"
USER_ID    = "user-sub-abc123"

VALID_REGO = "package contextiq.authz\ndefault allow = false"

SAMPLE_CHUNKS = [
    {
        "chunk_id":   str(uuid.uuid4()),
        "source_id":  str(uuid.uuid4()),
        "score":      0.91,
        "metadata":   {"classification_label": "internal"},
        "redacted":   False,
        "opa_denied": False,
    },
]

SAMPLE_STATE = {
    "request_id":   str(REQUEST_ID),
    "tenant_id":    TENANT_ID,
    "jwt_claims":   {"sub": USER_ID},
    "query":        "What is the deployment process?",
    "intent":       "technical_support",
    "ranked_context":                    SAMPLE_CHUNKS,
    "ranked_context_pre_compression":    SAMPLE_CHUNKS,
    "compression_tokens_before":         800,
    "compression_tokens_after":          400,
    "execution_trace":                   [{"node": "retrieval", "eval_ms": 45.0}],
    "governance_findings":               [],
    "governance_blocked":                False,
    "opa_denied_count":                  0,
    "opa_bundle_version":                "v1.0.0",
    "model_selected":                    "gpt-4o",
    "prompt_tokens":                     512,
    "completion_tokens":                 128,
    "response":                          "The deployment process involves ...",
}


@pytest.fixture
def moto_s3(monkeypatch):
    """Moto S3 mock — provides a functional aiobotocore-compatible S3 environment."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        # Create the bucket that TraceObjectStore expects
        s3 = boto3.client("s3", region_name="us-east-1",
                          endpoint_url="http://localhost:9000")
        s3.create_bucket(Bucket="contextiq-traces")
        s3.put_bucket_versioning(
            Bucket="contextiq-traces",
            VersioningConfiguration={"Status": "Enabled"},
        )
        yield s3
```

---

### AC-1 — Trace written to MinIO as JSON object

```python
# tests/audit/test_trace_object_store.py
async def test_write_produces_json_object(moto_s3):
    """AC-1: write() stores a valid JSON object in the S3/MinIO bucket."""
    from src.audit.trace.object_store  import TraceObjectStore, TraceObjectStoreSettings
    from src.audit.trace.schemas       import ExecutionTrace
    from src.audit.trace.writer_node   import _assemble_trace

    settings = TraceObjectStoreSettings(
        endpoint_url  = "http://localhost:9000",
        bucket        = "contextiq-traces",
        retention_days = 365,
    )
    store = TraceObjectStore(settings)
    trace = _assemble_trace(SAMPLE_STATE)

    result = await store.write(trace)

    # Verify the object exists
    obj = moto_s3.get_object(Bucket="contextiq-traces", Key=result.object_key)
    body = obj["Body"].read()
    import json
    parsed = json.loads(body)
    assert parsed["request_id"] == str(trace.request_id)
    assert parsed["intent"]     == "technical_support"
```

---

### AC-2 — All 10 required fields present in trace

```python
# tests/audit/test_trace_writer_node.py
def test_assemble_trace_contains_all_ac2_fields():
    """AC-2: ExecutionTrace contains all 10 required fields."""
    from src.audit.trace.writer_node import _assemble_trace

    trace = _assemble_trace(SAMPLE_STATE)

    assert trace.request_id        is not None
    assert trace.user_id           == USER_ID
    assert trace.timestamp         is not None
    assert trace.prompt            == SAMPLE_STATE["query"]
    assert trace.intent            == "technical_support"
    assert len(trace.execution_plan) > 0   # execution_plan
    # retrieved_chunks pre- and post-compression
    assert len(trace.retrieved_chunks_pre_compression)  > 0
    assert len(trace.retrieved_chunks_post_compression) > 0
    # governance_decisions
    assert trace.governance_decisions is not None
    assert trace.governance_decisions.opa_bundle_version == "v1.0.0"
    # model_selected
    assert trace.model_selected == "gpt-4o"
    # response_summary
    assert trace.response_summary is not None
    assert len(trace.response_summary) <= 500


def test_compression_delta_computed():
    """AC-2: compression delta captures before/after token counts."""
    from src.audit.trace.writer_node import _assemble_trace

    trace = _assemble_trace(SAMPLE_STATE)

    assert trace.compression_delta is not None
    assert trace.compression_delta.tokens_before == 800
    assert trace.compression_delta.tokens_after  == 400
    assert trace.compression_delta.reduction_pct == 50.0
```

---

### AC-3 — Write-once: new version not overwrite

```python
async def test_second_write_creates_new_version_not_overwrite(moto_s3):
    """AC-3: writing a second trace with the same request_id produces a new version_id."""
    from src.audit.trace.object_store  import TraceObjectStore, TraceObjectStoreSettings
    from src.audit.trace.writer_node   import _assemble_trace

    settings = TraceObjectStoreSettings(
        endpoint_url="http://localhost:9000",
        bucket="contextiq-traces",
    )
    store = TraceObjectStore(settings)
    trace = _assemble_trace(SAMPLE_STATE)

    result1 = await store.write(trace)
    result2 = await store.write(trace)   # same trace, second write

    # Bucket versioning must produce distinct version IDs
    assert result1.version_id != result2.version_id

    # Both versions must be retrievable
    versions = moto_s3.list_object_versions(
        Bucket="contextiq-traces", Prefix=result1.object_key
    )
    version_ids = [v["VersionId"] for v in versions.get("Versions", [])]
    assert result1.version_id in version_ids
    assert result2.version_id in version_ids
```

---

### AC-4 — PostgreSQL index searchable by all four columns

```python
# tests/audit/test_trace_index_repository.py
async def test_search_by_user_id(async_session):
    """AC-4: search() filters by user_id."""
    from src.audit.trace.repository import TraceIndexRepository, TraceSearchQuery
    from src.audit.trace.schemas    import TraceIndexEntry

    repo  = TraceIndexRepository(async_session)
    entry = TraceIndexEntry(
        request_id    = REQUEST_ID,
        tenant_id     = TENANT_ID,
        user_id       = USER_ID,
        timestamp     = datetime.now(tz=timezone.utc),
        intent        = "technical_support",
        object_key    = "traces/acme/2026/07/test.json",
        object_version = "v1",
    )
    await repo.upsert(entry)

    result = await repo.search(
        TENANT_ID,
        TraceSearchQuery(user_id=USER_ID),
    )
    assert result.total == 1
    assert result.items[0].request_id == REQUEST_ID


async def test_search_by_intent(async_session):
    """AC-4: search() filters by intent."""
    from src.audit.trace.repository import TraceIndexRepository, TraceSearchQuery
    from src.audit.trace.schemas    import TraceIndexEntry

    repo  = TraceIndexRepository(async_session)
    await repo.upsert(TraceIndexEntry(
        request_id=REQUEST_ID, tenant_id=TENANT_ID, user_id=USER_ID,
        timestamp=datetime.now(tz=timezone.utc), intent="billing_query",
        object_key="k", object_version="v1",
    ))
    result = await repo.search(TENANT_ID, TraceSearchQuery(intent="billing_query"))
    assert result.total == 1
    assert result.items[0].intent == "billing_query"


async def test_search_by_timestamp_range(async_session):
    """AC-4: search() filters by from_timestamp / to_timestamp."""
    from datetime import timedelta
    from src.audit.trace.repository import TraceIndexRepository, TraceSearchQuery
    from src.audit.trace.schemas    import TraceIndexEntry

    now  = datetime.now(tz=timezone.utc)
    repo = TraceIndexRepository(async_session)
    await repo.upsert(TraceIndexEntry(
        request_id=REQUEST_ID, tenant_id=TENANT_ID, user_id=USER_ID,
        timestamp=now, intent="billing_query",
        object_key="k2", object_version="v1",
    ))

    # Should find with range that includes `now`
    found = await repo.search(TENANT_ID, TraceSearchQuery(
        from_timestamp = now - timedelta(seconds=10),
        to_timestamp   = now + timedelta(seconds=10),
    ))
    assert found.total == 1

    # Should not find outside range
    not_found = await repo.search(TENANT_ID, TraceSearchQuery(
        from_timestamp = now + timedelta(hours=1),
    ))
    assert not_found.total == 0


async def test_upsert_is_idempotent(async_session):
    """AC-4: second upsert with same request_id does not create a duplicate row."""
    from src.audit.trace.repository import TraceIndexRepository, TraceSearchQuery
    from src.audit.trace.schemas    import TraceIndexEntry

    repo  = TraceIndexRepository(async_session)
    entry = TraceIndexEntry(
        request_id=REQUEST_ID, tenant_id=TENANT_ID, user_id=USER_ID,
        timestamp=datetime.now(tz=timezone.utc), intent="test",
        object_key="k3", object_version="v1",
    )
    await repo.upsert(entry)
    # Second upsert with updated object_version
    await repo.upsert(entry.model_copy(update={"object_version": "v2"}))

    result = await repo.search(TENANT_ID, TraceSearchQuery())
    rows = [r for r in result.items if r.request_id == REQUEST_ID]
    assert len(rows) == 1
    assert rows[0].object_version == "v2"
```

---

### AC-5 — Retention policy enforced at 90-day floor

```python
# tests/audit/test_trace_object_store.py (continued)
def test_retention_below_minimum_raises():
    """AC-5: retention_days < 90 raises ValueError."""
    from src.audit.trace.object_store import TraceObjectStore, TraceObjectStoreSettings

    with pytest.raises(ValueError, match="retention_days"):
        TraceObjectStore(TraceObjectStoreSettings(retention_days=30))


def test_default_retention_is_365_days():
    """AC-5: default retention is 1 year."""
    from src.audit.trace.object_store import TraceObjectStoreSettings

    settings = TraceObjectStoreSettings()
    assert settings.retention_days == 365
```

---

### AC-6 — Trace writes do not add latency to main request path

```python
# tests/audit/test_trace_writer_node.py (continued)
async def test_trace_writer_node_returns_without_waiting_for_persist():
    """AC-6: trace_writer_node() returns before _persist_trace completes."""
    import asyncio, time
    from unittest.mock import AsyncMock, patch
    from src.audit.trace.writer_node import (
        trace_writer_node, set_trace_object_store, set_trace_session_factory,
    )
    from src.audit.trace.object_store import TraceObjectStore, TraceWriteResult
    from datetime import datetime, timezone

    # Slow mock object store — simulates a delayed MinIO write
    slow_store = AsyncMock(spec=TraceObjectStore)
    async def _slow_write(trace):
        await asyncio.sleep(0.1)   # 100 ms
        return TraceWriteResult(
            object_key="k", version_id="v1", etag="e",
            written_at=datetime.now(tz=timezone.utc)
        )
    slow_store.write = AsyncMock(side_effect=_slow_write)

    session_mock = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__  = AsyncMock(return_value=False)
    session_mock.execute    = AsyncMock()
    session_mock.flush      = AsyncMock()
    session_mock.commit     = AsyncMock()
    factory_mock = AsyncMock(return_value=session_mock)

    set_trace_object_store(slow_store)
    set_trace_session_factory(lambda: session_mock)

    start  = time.monotonic()
    result = await trace_writer_node(SAMPLE_STATE)
    elapsed_ms = (time.monotonic() - start) * 1000

    # Node should return in < 10 ms even though _persist_trace sleeps 100 ms
    assert elapsed_ms < 10, f"trace_writer_node took {elapsed_ms:.1f} ms"
    assert result["trace_written"] is True

    # Allow background task to complete so test cleanup is clean
    await asyncio.sleep(0.15)


async def test_persist_trace_failure_does_not_raise():
    """AC-6: exception inside _persist_trace is swallowed — never propagates."""
    from unittest.mock import AsyncMock
    from src.audit.trace.writer_node  import _persist_trace
    from src.audit.trace.object_store import TraceObjectStore
    from src.audit.trace.writer_node  import _assemble_trace

    bad_store = AsyncMock(spec=TraceObjectStore)
    bad_store.write = AsyncMock(side_effect=RuntimeError("MinIO down"))

    state_with_bad_store = {
        **SAMPLE_STATE,
        "_config": {"trace_object_store": bad_store},
    }
    trace = _assemble_trace(state_with_bad_store)
    # Should complete without raising
    await _persist_trace(trace, state_with_bad_store)
```

## Acceptance Criteria

- [ ] All 6 AC-level test groups pass in CI without live MinIO or PostgreSQL
- [ ] `test_second_write_creates_new_version_not_overwrite` asserts two distinct `version_id` values
- [ ] `test_search_by_timestamp_range` covers both "within range" (found) and "outside range" (not found) cases
- [ ] `test_trace_writer_node_returns_without_waiting_for_persist` confirms < 10 ms node return time
- [ ] `test_persist_trace_failure_does_not_raise` completes without any exception propagating

## Dependencies

- TASK-US034-01 (`ExecutionTrace`, `TraceIndexEntry`, sub-schemas)
- TASK-US034-02 (`TraceObjectStore`, `TraceObjectStoreSettings`, `TraceWriteResult`)
- TASK-US034-03 (`TraceIndexRepository`, `TraceSearchQuery`)
- TASK-US034-04 (`trace_writer_node`, `_assemble_trace`, `_persist_trace`, `set_trace_object_store`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests mock MinIO via `moto[s3]` and PostgreSQL via `AsyncMock` — no live services in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
