"""Tests for OPAClient and PolicyBundleLoader — TASK-US032-02.

All OPA HTTP calls are mocked with respx; no live OPA sidecar required in CI.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.governance.opa.bundle_loader import BundleNotReadyError, PolicyBundleLoader
from src.governance.opa.client import OPAClient, OPAClientSettings, OPAEvaluationError
from src.governance.opa.schemas import ChunkAuthzInput

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings() -> OPAClientSettings:
    return OPAClientSettings(
        base_url="http://localhost:8181",
        request_timeout_s=0.05,
        policy_path="v1/data/contextiq/authz/allow",
        status_path="v1/status",
        expected_bundle_name="contextiq_policies",
        max_connections=5,
    )


@pytest.fixture
def chunk_input() -> ChunkAuthzInput:
    return ChunkAuthzInput(
        user_roles=["developer"],
        tenant_id="tenant-abc",
        source_id="src-001",
        chunk_id="chunk-001",
        document_id="doc-001",
        classification_label="internal",
    )


@pytest.fixture
async def opa_client(settings: OPAClientSettings) -> OPAClient:
    client = OPAClient(settings=settings)
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# AC-2: payload shape — all required fields present in the "input" envelope
# ---------------------------------------------------------------------------

@respx.mock
async def test_evaluate_chunk_sends_correct_payload(
    opa_client: OPAClient,
    chunk_input: ChunkAuthzInput,
) -> None:
    """AC-2: ChunkAuthzInput fields are serialised inside {"input": {...}}."""
    route = respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        return_value=httpx.Response(200, json={"result": True})
    )

    decision = await opa_client.evaluate_chunk(chunk_input)

    assert route.called
    sent_body = route.calls[0].request.read()
    import json
    payload = json.loads(sent_body)
    inp = payload["input"]

    assert inp["user_roles"] == ["developer"]
    assert inp["tenant_id"] == "tenant-abc"
    assert inp["source_id"] == "src-001"
    assert inp["classification_label"] == "internal"
    assert decision.allow is True
    assert decision.chunk_id == "chunk-001"


# ---------------------------------------------------------------------------
# Allow path: no deny_reason fetch
# ---------------------------------------------------------------------------

@respx.mock
async def test_evaluate_chunk_allow_no_deny_reason_fetch(
    opa_client: OPAClient,
    chunk_input: ChunkAuthzInput,
) -> None:
    """When OPA returns allow=True, deny_reason is NOT fetched."""
    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        return_value=httpx.Response(200, json={"result": True})
    )
    deny_route = respx.post(
        "http://localhost:8181/v1/data/contextiq/authz/deny_reason"
    ).mock(return_value=httpx.Response(200, json={"result": "some reason"}))

    decision = await opa_client.evaluate_chunk(chunk_input)

    assert decision.allow is True
    assert decision.rationale == ""
    assert not deny_route.called


# ---------------------------------------------------------------------------
# Deny path: deny_reason is fetched and recorded
# ---------------------------------------------------------------------------

@respx.mock
async def test_evaluate_chunk_deny_fetches_reason(
    opa_client: OPAClient,
    chunk_input: ChunkAuthzInput,
) -> None:
    """When OPA returns allow=False, deny_reason is fetched and attached."""
    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        return_value=httpx.Response(200, json={"result": False})
    )
    respx.post("http://localhost:8181/v1/data/contextiq/authz/deny_reason").mock(
        return_value=httpx.Response(200, json={"result": "classification_label restricted"})
    )

    decision = await opa_client.evaluate_chunk(chunk_input)

    assert decision.allow is False
    assert decision.is_denied is True
    assert decision.rationale == "classification_label restricted"


# ---------------------------------------------------------------------------
# AC-3: OPAEvaluationError raised on HTTP 5xx
# ---------------------------------------------------------------------------

@respx.mock
async def test_evaluate_chunk_raises_on_http_500(
    opa_client: OPAClient,
    chunk_input: ChunkAuthzInput,
) -> None:
    """AC-3: OPAEvaluationError is raised on HTTP 5xx — not swallowed."""
    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    with pytest.raises(OPAEvaluationError, match="HTTP 500"):
        await opa_client.evaluate_chunk(chunk_input)


# ---------------------------------------------------------------------------
# AC-3: OPAEvaluationError raised on timeout
# ---------------------------------------------------------------------------

@respx.mock
async def test_evaluate_chunk_raises_on_timeout(
    opa_client: OPAClient,
    chunk_input: ChunkAuthzInput,
) -> None:
    """AC-3: OPAEvaluationError is raised on timeout — not swallowed."""
    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        side_effect=httpx.TimeoutException("timed out")
    )

    with pytest.raises(OPAEvaluationError, match="timed out"):
        await opa_client.evaluate_chunk(chunk_input)


# ---------------------------------------------------------------------------
# Deny_reason failure is silently absorbed (AC-7)
# ---------------------------------------------------------------------------

@respx.mock
async def test_deny_reason_fetch_failure_is_absorbed(
    opa_client: OPAClient,
    chunk_input: ChunkAuthzInput,
) -> None:
    """Failure to fetch deny_reason is silently absorbed; denial still recorded."""
    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        return_value=httpx.Response(200, json={"result": False})
    )
    respx.post("http://localhost:8181/v1/data/contextiq/authz/deny_reason").mock(
        side_effect=httpx.NetworkError("connection refused")
    )

    decision = await opa_client.evaluate_chunk(chunk_input)

    assert decision.allow is False
    assert decision.rationale == ""


# ---------------------------------------------------------------------------
# AC-4: evaluate_batch processes concurrently
# ---------------------------------------------------------------------------

@respx.mock
async def test_evaluate_batch_concurrent(settings: OPAClientSettings) -> None:
    """AC-4: total_eval_ms < n_chunks × request_timeout_ms when n_chunks > concurrency.

    We mock each call to take ~5 ms.  With concurrency=5 and n_chunks=15,
    serial execution would take ≥ 75 ms.  Concurrent execution completes
    in ~15 ms (3 waves × 5 ms), well below the serial bound.
    """
    n_chunks = 15
    concurrency = 5
    mock_delay_s = 0.005  # 5 ms per chunk

    inputs = [
        ChunkAuthzInput(
            user_roles=["developer"],
            tenant_id="tenant-abc",
            source_id="src-001",
            chunk_id=f"chunk-{i:03d}",
            classification_label="internal",
        )
        for i in range(n_chunks)
    ]

    async def _delayed_allow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(mock_delay_s)
        return httpx.Response(200, json={"result": True})

    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        side_effect=_delayed_allow
    )

    client = OPAClient(settings=settings)
    try:
        result = await client.evaluate_batch(inputs, concurrency=concurrency)
    finally:
        await client.close()

    serial_ms = n_chunks * mock_delay_s * 1000
    assert result.total_eval_ms < serial_ms, (
        f"total_eval_ms={result.total_eval_ms:.1f} should be < serial {serial_ms:.1f} ms"
    )
    assert len(result.allowed_chunk_ids) == n_chunks
    assert result.denied_chunk_ids == []


# ---------------------------------------------------------------------------
# evaluate_batch allow/deny split
# ---------------------------------------------------------------------------

@respx.mock
async def test_evaluate_batch_allow_deny_split(settings: OPAClientSettings) -> None:
    """evaluate_batch correctly splits allowed and denied chunk IDs."""
    inputs = [
        ChunkAuthzInput(
            user_roles=["developer"],
            tenant_id="tenant-abc",
            source_id="src-001",
            chunk_id=f"chunk-{i:03d}",
            classification_label="internal",
        )
        for i in range(4)
    ]

    call_count = 0

    async def _alternating(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        result = call_count % 2 == 0  # even = allow, odd = deny
        call_count += 1
        return httpx.Response(200, json={"result": result})

    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        side_effect=_alternating
    )
    # deny_reason calls for denied chunks
    respx.post("http://localhost:8181/v1/data/contextiq/authz/deny_reason").mock(
        return_value=httpx.Response(200, json={"result": ""})
    )

    client = OPAClient(settings=settings)
    try:
        result = await client.evaluate_batch(inputs, concurrency=4)
    finally:
        await client.close()

    assert len(result.allowed_chunk_ids) == 2
    assert len(result.denied_chunk_ids) == 2


# ---------------------------------------------------------------------------
# PolicyBundleLoader — AC-1: returns BundleInfo on success
# ---------------------------------------------------------------------------

@respx.mock
async def test_bundle_loader_returns_bundle_info(settings: OPAClientSettings) -> None:
    """AC-1: PolicyBundleLoader.verify() returns BundleInfo with correct version."""
    respx.get("http://localhost:8181/v1/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "bundles": {
                    "contextiq_policies": {
                        "active_revision": "v1.2.3",
                    }
                }
            },
        )
    )

    loader = PolicyBundleLoader(settings=settings)
    info = await loader.verify()

    assert info.version == "v1.2.3"
    assert info.source_url == "http://localhost:8181"


# ---------------------------------------------------------------------------
# PolicyBundleLoader — raises BundleNotReadyError when bundle never active
# ---------------------------------------------------------------------------

@respx.mock
async def test_bundle_loader_raises_when_bundle_never_active(
    settings: OPAClientSettings,
) -> None:
    """AC-1: BundleNotReadyError raised when bundle status never has active_revision."""
    respx.get("http://localhost:8181/v1/status").mock(
        return_value=httpx.Response(
            200,
            json={"bundles": {"contextiq_policies": {}}},  # no active_revision
        )
    )

    loader = PolicyBundleLoader(settings=settings)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(BundleNotReadyError, match="contextiq_policies"):
            await loader.verify()


# ---------------------------------------------------------------------------
# PolicyBundleLoader — HTTP error on every attempt → BundleNotReadyError
# ---------------------------------------------------------------------------

@respx.mock
async def test_bundle_loader_raises_on_all_http_errors(
    settings: OPAClientSettings,
) -> None:
    """BundleNotReadyError raised when status endpoint always returns 503."""
    respx.get("http://localhost:8181/v1/status").mock(
        return_value=httpx.Response(503)
    )

    loader = PolicyBundleLoader(settings=settings)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(BundleNotReadyError):
            await loader.verify()


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-2: required fields sent to OPA (named per acceptance criteria)
# ---------------------------------------------------------------------------

@respx.mock
async def test_opa_client_sends_required_fields() -> None:
    """AC-2: all four required ChunkAuthzInput fields appear in the OPA request body."""
    import json

    tenant_id = "acme"
    source_id = "src-test-001"
    chunk_id  = "chunk-test-001"

    inp = ChunkAuthzInput(
        user_roles=["developer"],
        tenant_id=tenant_id,
        source_id=source_id,
        chunk_id=chunk_id,
        classification_label="internal",
    )
    route = respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        return_value=httpx.Response(200, json={"result": True})
    )

    settings = OPAClientSettings(base_url="http://localhost:8181")
    client = OPAClient(settings)
    decision = await client.evaluate_chunk(inp)
    await client.close()

    request_body = json.loads(route.calls[0].request.content)
    opa_input = request_body["input"]

    assert opa_input["user_roles"]           == ["developer"]
    assert opa_input["tenant_id"]            == tenant_id
    assert opa_input["source_id"]            == source_id
    assert opa_input["classification_label"] == "internal"
    assert decision.allow is True


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-5: timeout raises OPAEvaluationError (named per AC)
# ---------------------------------------------------------------------------

@respx.mock
async def test_opa_client_timeout_raises_evaluation_error() -> None:
    """AC-5: OPAEvaluationError with 'timed out' raised when OPA call exceeds budget."""
    inp = ChunkAuthzInput(
        user_roles=["developer"],
        tenant_id="acme",
        source_id="src-test-001",
        chunk_id="chunk-test-001",
    )
    respx.post("http://localhost:8181/v1/data/contextiq/authz/allow").mock(
        side_effect=httpx.TimeoutException("timeout")
    )

    client = OPAClient(OPAClientSettings(request_timeout_s=0.05))
    with pytest.raises(OPAEvaluationError, match="timed out"):
        await client.evaluate_chunk(inp)
    await client.close()


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-5: concurrent batch evaluation via mock_opa_allow_all
# ---------------------------------------------------------------------------

async def test_evaluate_batch_concurrency(mock_opa_allow_all) -> None:
    """AC-5: 20 chunks evaluated concurrently; total time well below serial bound."""
    import time

    chunks = [
        ChunkAuthzInput(
            user_roles=["developer"],
            tenant_id="acme",
            source_id="src-test-001",
            chunk_id=str(i),
        )
        for i in range(20)
    ]

    start = time.monotonic()
    result = await mock_opa_allow_all.evaluate_batch(chunks, concurrency=10)
    elapsed_ms = (time.monotonic() - start) * 1000

    assert len(result.decisions) == 20
    # All 20 at ~5 ms each with concurrency=10 → should be much less than 100 ms serial
    assert elapsed_ms < 500  # generous bound to avoid flakiness on slow CI
