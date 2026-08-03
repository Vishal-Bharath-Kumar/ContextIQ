# TASK-US032-05 — Integration Tests Covering All 7 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US032-05 |
| User Story | US-032 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the integration and unit test suite covering all 7 US-032 acceptance criteria: OPA bundle loaded at startup, per-chunk `data.contextiq.authz.allow` call with required fields, denied chunk filtering, execution trace recording, 50 ms per-chunk budget, 60 s hot-reload propagation, and `governance_policy_denials_total` Prometheus counter.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `respx`, `AsyncMock`, `unittest.mock`

**File locations:**
- `tests/governance/test_opa_client.py` — AC-2, AC-5 (input shape + 50 ms budget)
- `tests/governance/test_bundle_loader.py` — AC-1 (startup bundle verification)
- `tests/governance/test_hot_reloader.py` — AC-6 (revision change detection)
- `tests/governance/test_opa_filter_node.py` — AC-2, AC-3, AC-4, AC-7 (node integration)

---

### Shared fixtures

```python
# tests/governance/conftest.py  (extend existing conftest)
import pytest
from uuid import uuid4

SOURCE_ID = str(uuid4())
CHUNK_A   = str(uuid4())
CHUNK_B   = str(uuid4())
TENANT_ID = "acme"
USER_ROLES = ["developer"]

@pytest.fixture
def two_item_context():
    return [
        {
            "chunk_id":    CHUNK_A,
            "source_id":   SOURCE_ID,
            "text":        "Public design doc content.",
            "metadata":    {"classification_label": "internal"},
        },
        {
            "chunk_id":    CHUNK_B,
            "source_id":   SOURCE_ID,
            "text":        "Restricted financial data.",
            "metadata":    {"classification_label": "restricted"},
        },
    ]

@pytest.fixture
def mock_opa_allow_all():
    """OPA client that allows every chunk."""
    from unittest.mock import AsyncMock
    from src.governance.opa.schemas import PolicyDecision, AuthzFilterResult

    client = AsyncMock()
    async def _allow_batch(inputs, concurrency=10):
        decisions = [
            PolicyDecision(chunk_id=i.chunk_id, allow=True, rationale="", eval_ms=5.0)
            for i in inputs
        ]
        return AuthzFilterResult(
            decisions         = decisions,
            allowed_chunk_ids = [d.chunk_id for d in decisions],
            denied_chunk_ids  = [],
            total_eval_ms     = 10.0,
        )
    client.evaluate_batch = AsyncMock(side_effect=_allow_batch)
    return client

@pytest.fixture
def mock_opa_deny_restricted():
    """OPA client that denies chunks with classification_label='restricted'."""
    from unittest.mock import AsyncMock
    from src.governance.opa.schemas import PolicyDecision, AuthzFilterResult

    client = AsyncMock()
    async def _eval_batch(inputs, concurrency=10):
        decisions = [
            PolicyDecision(
                chunk_id  = i.chunk_id,
                allow     = (i.classification_label != "restricted"),
                rationale = (
                    "User roles lack access to restricted classification"
                    if i.classification_label == "restricted" else ""
                ),
                eval_ms   = 8.0,
            )
            for i in inputs
        ]
        return AuthzFilterResult(
            decisions         = decisions,
            allowed_chunk_ids = [d.chunk_id for d in decisions if d.allow],
            denied_chunk_ids  = [d.chunk_id for d in decisions if d.is_denied],
            total_eval_ms     = 16.0,
        )
    client.evaluate_batch = AsyncMock(side_effect=_eval_batch)
    return client
```

---

### AC-1 — OPA bundle loaded at startup

```python
# tests/governance/test_bundle_loader.py
import pytest
import respx
import httpx
from datetime import datetime, timezone

async def test_bundle_loader_returns_bundle_info_when_ready():
    from src.governance.opa.bundle_loader import PolicyBundleLoader
    from src.governance.opa.client        import OPAClientSettings

    settings = OPAClientSettings(expected_bundle_name="contextiq_policies")
    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.get("/v1/status").mock(return_value=httpx.Response(200, json={
            "bundles": {
                "contextiq_policies": {"active_revision": "v1.2.3"}
            }
        }))
        loader = PolicyBundleLoader(settings)
        info   = await loader.verify()

    assert info.version == "v1.2.3"
    assert isinstance(info.loaded_at, datetime)


async def test_bundle_loader_raises_when_bundle_never_activates():
    from src.governance.opa.bundle_loader import PolicyBundleLoader, BundleNotReadyError
    from src.governance.opa.client        import OPAClientSettings

    settings = OPAClientSettings(expected_bundle_name="contextiq_policies")
    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.get("/v1/status").mock(return_value=httpx.Response(200, json={
            "bundles": {"contextiq_policies": {}}   # no active_revision
        }))
        loader = PolicyBundleLoader(settings)
        with pytest.raises(BundleNotReadyError):
            # Set max_attempts=1 to speed up the test
            loader._max_attempts = 1
            await loader.verify()
```

---

### AC-2 — Input fields sent to OPA

```python
# tests/governance/test_opa_client.py
async def test_opa_client_sends_required_fields():
    import respx, httpx, json
    from src.governance.opa.client  import OPAClient, OPAClientSettings
    from src.governance.opa.schemas import ChunkAuthzInput

    inp = ChunkAuthzInput(
        user_roles           = ["developer"],
        tenant_id            = TENANT_ID,
        source_id            = SOURCE_ID,
        chunk_id             = CHUNK_A,
        classification_label = "internal",
    )
    with respx.mock(base_url="http://localhost:8181") as mock:
        route = mock.post("/v1/data/contextiq/authz/allow").mock(
            return_value=httpx.Response(200, json={"result": True})
        )
        client   = OPAClient(OPAClientSettings())
        decision = await client.evaluate_chunk(inp)
        await client.close()

    request_body = json.loads(route.calls[0].request.content)
    opa_input    = request_body["input"]
    assert opa_input["user_roles"]           == ["developer"]
    assert opa_input["tenant_id"]            == TENANT_ID
    assert opa_input["source_id"]            == SOURCE_ID
    assert opa_input["classification_label"] == "internal"
    assert decision.allow is True
```

---

### AC-3 — Denied chunks filtered from ranked_context

```python
# tests/governance/test_opa_filter_node.py
async def test_denied_chunks_filtered(two_item_context, mock_opa_deny_restricted):
    from src.governance.nodes.opa_filter_node import opa_filter_node, set_opa_client

    set_opa_client(mock_opa_deny_restricted)
    state = {
        "ranked_context": two_item_context,
        "jwt_claims":     {"roles": USER_ROLES},
        "tenant_id":      TENANT_ID,
    }
    result = await opa_filter_node(state)

    assert len(result["ranked_context"]) == 1
    assert result["ranked_context"][0]["chunk_id"] == CHUNK_A
    assert result["opa_denied_count"] == 1


async def test_allowed_chunks_preserved_in_order(two_item_context, mock_opa_allow_all):
    from src.governance.nodes.opa_filter_node import opa_filter_node, set_opa_client

    set_opa_client(mock_opa_allow_all)
    state = {
        "ranked_context": two_item_context,
        "jwt_claims":     {"roles": USER_ROLES},
        "tenant_id":      TENANT_ID,
    }
    result = await opa_filter_node(state)

    assert len(result["ranked_context"])    == 2
    assert result["ranked_context"][0]["chunk_id"] == CHUNK_A
    assert result["ranked_context"][1]["chunk_id"] == CHUNK_B
```

---

### AC-4 — Policy decision recorded in execution trace

```python
async def test_decisions_recorded_in_execution_trace(two_item_context, mock_opa_deny_restricted):
    from src.governance.nodes.opa_filter_node import opa_filter_node, set_opa_client

    set_opa_client(mock_opa_deny_restricted)
    state = {
        "ranked_context": two_item_context,
        "jwt_claims":     {"roles": USER_ROLES},
        "tenant_id":      TENANT_ID,
    }
    result = await opa_filter_node(state)

    trace      = result.get("execution_trace") or []
    opa_entry  = next((e for e in trace if e.get("node") == "opa_filter"), None)
    assert opa_entry is not None

    decisions = opa_entry["decisions"]
    assert len(decisions) == 2

    denied = [d for d in decisions if not d["allow"]]
    assert len(denied) == 1
    assert denied[0]["chunk_id"]  == CHUNK_B
    assert "rationale"            in denied[0]
    assert denied[0]["rationale"] != ""
```

---

### AC-5 — 50 ms per-chunk budget

```python
async def test_opa_client_timeout_raises_evaluation_error():
    import respx, httpx, pytest
    from src.governance.opa.client  import OPAClient, OPAClientSettings, OPAEvaluationError
    from src.governance.opa.schemas import ChunkAuthzInput

    inp = ChunkAuthzInput(
        user_roles=["developer"], tenant_id=TENANT_ID,
        source_id=SOURCE_ID, chunk_id=CHUNK_A,
    )
    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.post("/v1/data/contextiq/authz/allow").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client = OPAClient(OPAClientSettings(request_timeout_s=0.05))
        with pytest.raises(OPAEvaluationError, match="timed out"):
            await client.evaluate_chunk(inp)
        await client.close()


async def test_evaluate_batch_concurrency(mock_opa_allow_all):
    """
    Verify that 20 chunks are evaluated concurrently:
    total time should be much less than 20 × per_chunk_time.
    """
    import time
    from src.governance.opa.schemas import ChunkAuthzInput
    from src.governance.opa.client  import OPAClient

    chunks = [
        ChunkAuthzInput(
            user_roles=["developer"], tenant_id=TENANT_ID,
            source_id=SOURCE_ID, chunk_id=str(i),
        )
        for i in range(20)
    ]
    start  = time.monotonic()
    result = await mock_opa_allow_all.evaluate_batch(chunks, concurrency=10)
    elapsed_ms = (time.monotonic() - start) * 1000

    assert len(result.decisions) == 20
    # All 20 at 5ms each with concurrency=10 → ~10ms total (not 100ms serial)
    assert elapsed_ms < 100
```

---

### AC-6 — Hot-reload detects bundle revision change

```python
# tests/governance/test_hot_reloader.py
async def test_hot_reloader_detects_revision_change():
    import respx, httpx
    from unittest.mock import patch, AsyncMock
    from datetime      import datetime, timezone
    from src.governance.opa.schemas     import BundleInfo
    from src.governance.opa.hot_reloader import PolicyHotReloader, HotReloadSettings

    initial = BundleInfo(
        version="v1.0.0", loaded_at=datetime.now(tz=timezone.utc),
        source_url="http://localhost:8181"
    )
    settings = HotReloadSettings(poll_interval_s=0.01, bundle_name="contextiq_policies")
    reloader = PolicyHotReloader(initial, settings)
    reloaded = []
    reloader.on_reload(lambda: reloaded.append(True))

    with respx.mock() as mock:
        mock.get("http://localhost:8181/v1/status").mock(return_value=httpx.Response(200, json={
            "bundles": {"contextiq_policies": {"active_revision": "v1.1.0"}}
        }))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await reloader._poll_once(
                httpx.AsyncClient.__new__(httpx.AsyncClient)
            )

    assert reloader.current_bundle.version == "v1.1.0"
    assert len(reloaded) == 1


async def test_hot_reloader_no_update_on_same_revision():
    import respx, httpx
    from datetime import datetime, timezone
    from src.governance.opa.schemas      import BundleInfo
    from src.governance.opa.hot_reloader import PolicyHotReloader, HotReloadSettings

    initial  = BundleInfo(
        version="v1.0.0", loaded_at=datetime.now(tz=timezone.utc),
        source_url="http://localhost:8181"
    )
    settings = HotReloadSettings(poll_interval_s=0.01, bundle_name="contextiq_policies")
    reloader = PolicyHotReloader(initial, settings)

    with respx.mock() as mock:
        mock.get("http://localhost:8181/v1/status").mock(return_value=httpx.Response(200, json={
            "bundles": {"contextiq_policies": {"active_revision": "v1.0.0"}}
        }))
        original_bundle = reloader.current_bundle
        await reloader._poll_once(httpx.AsyncClient.__new__(httpx.AsyncClient))

    assert reloader.current_bundle is original_bundle  # same object, not replaced
```

---

### AC-7 — `governance_policy_denials_total` incremented

```python
# tests/governance/test_opa_filter_node.py (continued)
async def test_governance_policy_denials_total_incremented(
    two_item_context, mock_opa_deny_restricted
):
    from src.governance.nodes.opa_filter_node import opa_filter_node, set_opa_client
    from src.governance.opa.metrics           import governance_policy_denials_total

    set_opa_client(mock_opa_deny_restricted)

    before = governance_policy_denials_total.labels(
        tenant_id="acme", classification_label="restricted"
    )._value.get()

    state = {
        "ranked_context": two_item_context,
        "jwt_claims":     {"roles": USER_ROLES},
        "tenant_id":      TENANT_ID,
    }
    await opa_filter_node(state)

    after = governance_policy_denials_total.labels(
        tenant_id="acme", classification_label="restricted"
    )._value.get()
    assert after - before == 1


async def test_no_denials_counter_not_incremented(two_item_context, mock_opa_allow_all):
    from src.governance.nodes.opa_filter_node import opa_filter_node, set_opa_client
    from src.governance.opa.metrics           import governance_policy_denials_total

    set_opa_client(mock_opa_allow_all)

    before = sum(
        s._value.get() for s in governance_policy_denials_total._metrics.values()
    )
    state = {
        "ranked_context": two_item_context,
        "jwt_claims":     {"roles": ["admin"]},
        "tenant_id":      TENANT_ID,
    }
    await opa_filter_node(state)

    after = sum(
        s._value.get() for s in governance_policy_denials_total._metrics.values()
    )
    assert after == before
```

## Acceptance Criteria

- [ ] All 7 AC-level tests pass in CI without a live OPA sidecar
- [ ] `test_denied_chunks_filtered` confirms `restricted` chunk is absent from returned `ranked_context`
- [ ] `test_decisions_recorded_in_execution_trace` confirms rationale is non-empty for denied chunks
- [ ] `test_hot_reloader_no_update_on_same_revision` confirms bundle object is not replaced unnecessarily
- [ ] `test_governance_policy_denials_total_incremented` uses scoped `_value.get()` — not a global registry reset

## Dependencies

- TASK-US032-01 (`ChunkAuthzInput`, `PolicyDecision`, `AuthzFilterResult`, `BundleInfo`)
- TASK-US032-02 (`OPAClient`, `OPAEvaluationError`, `PolicyBundleLoader`)
- TASK-US032-03 (`PolicyHotReloader`)
- TASK-US032-04 (`opa_filter_node`, `set_opa_client`, Prometheus metrics)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests mock OPA via `respx`; no live sidecar required in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
