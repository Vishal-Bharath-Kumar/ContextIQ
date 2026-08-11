"""Unit tests for PolicyPreviewService — TASK-US040-04.

Covers:
- Correct allow/deny counting when OPA returns mixed results
- Division-by-zero guard when there are no traces
- Temporary policy is deleted even when evaluation raises
- affected_request_ids contains only the denied trace request_ids
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from src.audit.trace.schemas import ExecutionTrace, RetrievedChunkSummary
from src.governance.policy.preview_service import (
    _TEMP_POLICY_PREFIX,
    PolicyPreviewService,
)
from src.governance.policy.schemas import PolicyPreviewRequest

_OPA_BASE = "http://localhost:8181"
_POLICY_ID = uuid.uuid4()
_TEMP_NAME = f"{_TEMP_POLICY_PREFIX}{_POLICY_ID.hex}"
_PREVIEW_DATA_PATH = f"preview/{_TEMP_NAME}"
_REGO_BODY = "package test\n\ndefault allow = true\n"


def _make_trace_row(
    *,
    request_id: uuid.UUID | None = None,
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    intent: str = "query",
) -> MagicMock:
    row = MagicMock()
    row.request_id = request_id or uuid.uuid4()
    row.user_id = user_id
    row.tenant_id = tenant_id
    row.intent = intent
    row.timestamp = datetime.now(tz=UTC)
    return row


def _make_service(
    session: AsyncMock,
    opa_client: httpx.AsyncClient,
) -> PolicyPreviewService:
    return PolicyPreviewService(
        session=session,
        opa_client=opa_client,
        opa_base=_OPA_BASE,
    )


# ------------------------------------------------------------------ #
# Tests                                                               #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
@respx.mock
async def test_preview_allow_and_deny_counts() -> None:
    """Two traces: first allowed, second denied — counts and percentages correct."""
    req_allow = uuid.uuid4()
    req_deny = uuid.uuid4()
    traces = [
        _make_trace_row(request_id=req_allow),
        _make_trace_row(request_id=req_deny),
    ]

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = traces
    session.execute = AsyncMock(return_value=mock_result)

    # OPA PUT temp policy
    respx.put(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    # OPA DELETE temp policy
    respx.delete(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    # First trace → allow=True, second → allow=False
    respx.post(f"{_OPA_BASE}/v1/data/{_PREVIEW_DATA_PATH}/allow").mock(
        side_effect=[
            httpx.Response(200, json={"result": True}),
            httpx.Response(200, json={"result": False}),
        ]
    )

    async with httpx.AsyncClient(trust_env=False) as client:
        svc = _make_service(session, client)
        result = await svc.preview(
            _POLICY_ID, PolicyPreviewRequest(rego_body=_REGO_BODY)
        )

    assert result.evaluated_count == 2
    assert result.allow_count == 1
    assert result.deny_count == 1
    assert result.allow_pct == 50.0
    assert result.deny_pct == 50.0
    assert result.affected_request_ids == [str(req_deny)]


@pytest.mark.asyncio
@respx.mock
async def test_preview_zero_traces_returns_zero_counts() -> None:
    """When no traces exist the result is all zeros without dividing by zero."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    respx.put(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    respx.delete(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)

    async with httpx.AsyncClient(trust_env=False) as client:
        svc = _make_service(session, client)
        result = await svc.preview(
            _POLICY_ID, PolicyPreviewRequest(rego_body=_REGO_BODY)
        )

    assert result.evaluated_count == 0
    assert result.allow_count == 0
    assert result.deny_count == 0
    assert result.allow_pct == 0.0
    assert result.deny_pct == 0.0
    assert result.affected_request_ids == []


@pytest.mark.asyncio
@respx.mock
async def test_preview_temp_policy_deleted_even_when_evaluation_raises() -> None:
    """Temporary OPA policy is always deleted even when evaluation raises."""
    traces = [_make_trace_row()]

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = traces
    session.execute = AsyncMock(return_value=mock_result)

    respx.put(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    delete_route = respx.delete(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    # POST for evaluation raises a network error
    respx.post(f"{_OPA_BASE}/v1/data/{_PREVIEW_DATA_PATH}/allow").mock(
        side_effect=httpx.ConnectError("network failure")
    )

    async with httpx.AsyncClient(trust_env=False) as client:
        svc = _make_service(session, client)
        result = await svc.preview(
            _POLICY_ID, PolicyPreviewRequest(rego_body=_REGO_BODY)
        )

    # Network error treated as deny
    assert result.deny_count == 1
    # Delete was still called
    assert delete_route.called


@pytest.mark.asyncio
@respx.mock
async def test_preview_all_allowed_no_affected_ids() -> None:
    """When all traces are allowed, affected_request_ids is empty."""
    traces = [_make_trace_row() for _ in range(3)]

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = traces
    session.execute = AsyncMock(return_value=mock_result)

    respx.put(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    respx.delete(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    respx.post(f"{_OPA_BASE}/v1/data/{_PREVIEW_DATA_PATH}/allow").mock(
        side_effect=[httpx.Response(200, json={"result": True})] * 3
    )

    async with httpx.AsyncClient(trust_env=False) as client:
        svc = _make_service(session, client)
        result = await svc.preview(
            _POLICY_ID, PolicyPreviewRequest(rego_body=_REGO_BODY)
        )

    assert result.allow_count == 3
    assert result.deny_count == 0
    assert result.affected_request_ids == []


@pytest.mark.asyncio
@respx.mock
async def test_preview_uses_chunk_authz_contract_from_full_trace() -> None:
    """Full traces are replayed as chunk-auth inputs with roles and classification labels."""
    req_id = uuid.uuid4()
    row = _make_trace_row(request_id=req_id, tenant_id="tenant-42")

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [row]
    session.execute = AsyncMock(return_value=mock_result)

    object_store = AsyncMock()
    object_store.read = AsyncMock(
        return_value=ExecutionTrace(
            request_id=req_id,
            tenant_id="tenant-42",
            user_id="user-42",
            user_roles=["security_officer"],
            timestamp=datetime.now(tz=UTC),
            prompt="preview",
            intent="query",
            retrieved_chunks_pre_compression=[
                RetrievedChunkSummary(
                    chunk_id="chunk-1",
                    source_id="src-1",
                    relevance_score=0.8,
                    classification_label="restricted",
                ),
                RetrievedChunkSummary(
                    chunk_id="chunk-2",
                    source_id="src-2",
                    relevance_score=0.5,
                    classification_label="internal",
                ),
            ],
        )
    )

    captured_inputs: list[dict[str, object]] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        captured_inputs.append(payload["input"])
        return httpx.Response(200, json={"result": True})

    respx.put(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    respx.delete(f"{_OPA_BASE}/v1/policies/{_TEMP_NAME}").respond(200)
    respx.post(f"{_OPA_BASE}/v1/data/{_PREVIEW_DATA_PATH}/allow").mock(side_effect=_capture)

    async with httpx.AsyncClient(trust_env=False) as client:
        svc = PolicyPreviewService(
            session=session,
            opa_client=client,
            opa_base=_OPA_BASE,
            object_store=object_store,
        )
        result = await svc.preview(
            _POLICY_ID, PolicyPreviewRequest(rego_body=_REGO_BODY)
        )

    assert result.evaluated_count == 1
    assert result.allow_count == 1
    assert captured_inputs == [
        {
            "user_roles": ["security_officer"],
            "tenant_id": "tenant-42",
            "source_id": "src-1",
            "chunk_id": "chunk-1",
            "document_id": "",
            "classification_label": "restricted",
        },
        {
            "user_roles": ["security_officer"],
            "tenant_id": "tenant-42",
            "source_id": "src-2",
            "chunk_id": "chunk-2",
            "document_id": "",
            "classification_label": "internal",
        },
    ]
