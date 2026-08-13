"""Unit tests for trace_writer_node + _persist_trace — TASK-US034-04.

Validates:
- AC-2: _assemble_trace maps all required fields from AgentState.
- AC-6: trace_writer_node returns within < 5 ms (fire-and-forget dispatch).
- AC-6: exceptions inside _persist_trace are swallowed, not propagated.
- AC-7: trace_written is True in returned state once task is enqueued.
- Injectable singletons allow testing without live MinIO or PostgreSQL.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.audit.trace.writer_node as _mod
from src.agents.schemas.intent import IntentType
from src.audit.trace.object_store import TraceWriteResult
from src.audit.trace.writer_node import (
    _assemble_trace,
    _persist_trace,
    set_trace_object_store,
    set_trace_session_factory,
    trace_writer_node,
)

# ------------------------------------------------------------------ #
# Helpers / fixtures                                                   #
# ------------------------------------------------------------------ #


def _make_state(**overrides: object) -> dict:  # type: ignore[type-arg]
    """Return a minimal AgentState-compatible dict for testing."""
    base: dict = {
        "request_id": str(uuid.uuid4()),
        "jwt_claims": {"sub": "user-123"},
        "tenant_id": "tenant-abc",
        "query": "What is the policy?",
        "intent": "policy_lookup",
        "model_selected": "gpt-4o",
        "ranked_context": [
            {
                "chunk_id": "c1",
                "source_id": "src1",
                "score": 0.92,
                "redacted": False,
                "opa_denied": False,
                "metadata": {"classification_label": "internal"},
            }
        ],
        "ranked_context_pre_compression": [
            {
                "chunk_id": "c1",
                "source_id": "src1",
                "score": 0.92,
                "redacted": False,
                "opa_denied": False,
                "metadata": {"classification_label": "internal"},
            },
            {
                "chunk_id": "c2",
                "source_id": "src2",
                "score": 0.71,
                "redacted": False,
                "opa_denied": False,
                "metadata": {"classification_label": "internal"},
            },
        ],
        "compression_tokens_before": 1200,
        "compression_tokens_after": 800,
        "governance_findings": [],
        "governance_blocked": False,
        "opa_denied_count": 0,
        "opa_bundle_version": "v1.2.3",
        "execution_trace": [{"node": "intent_agent", "eval_ms": 12.3}],
        "response": "Here is the policy summary.",
        "prompt_tokens": 300,
        "completion_tokens": 150,
        "total_latency_ms": 420.5,
        "_config": {},
    }
    base.update(overrides)
    return base


def _make_write_result() -> TraceWriteResult:
    return TraceWriteResult(
        object_key="traces/tenant-abc/2026/07/some-id.json",
        version_id="v-001",
        etag="abc123",
        written_at=datetime.now(tz=UTC),
    )


@pytest.fixture(autouse=True)
def reset_singletons() -> Generator[None, None, None]:
    """Reset module-level singletons between tests."""
    orig_store = _mod._DEFAULT_OBJECT_STORE
    orig_factory = _mod._DEFAULT_SESSION_FACTORY
    yield
    _mod._DEFAULT_OBJECT_STORE = orig_store
    _mod._DEFAULT_SESSION_FACTORY = orig_factory


# ------------------------------------------------------------------ #
# _assemble_trace — AC-2 field mapping                                #
# ------------------------------------------------------------------ #


def test_assemble_trace_maps_required_fields() -> None:
    state = _make_state(intent_confidence=0.82)
    trace = _assemble_trace(state)

    assert isinstance(trace.request_id, uuid.UUID)
    assert trace.tenant_id == "tenant-abc"
    assert trace.user_id == "user-123"
    assert trace.intent == "policy_lookup"
    assert trace.intent_confidence == pytest.approx(0.82)
    assert trace.prompt == "What is the policy?"
    assert trace.model_selected == "gpt-4o"
    assert trace.prompt_tokens == 300
    assert trace.completion_tokens == 150
    assert trace.latency_ms == 420.5
    assert trace.response_summary == "Here is the policy summary."


def test_assemble_trace_retrieved_chunks() -> None:
    state = _make_state()
    trace = _assemble_trace(state)

    # pre-compression: 2 chunks
    assert len(trace.retrieved_chunks_pre_compression) == 2
    assert trace.retrieved_chunks_pre_compression[0].chunk_id == "c1"
    # post-compression: 1 chunk
    assert len(trace.retrieved_chunks_post_compression) == 1


def test_assemble_trace_compression_delta() -> None:
    state = _make_state()
    trace = _assemble_trace(state)

    assert trace.compression_delta is not None
    assert trace.compression_delta.tokens_before == 1200
    assert trace.compression_delta.tokens_after == 800
    assert trace.compression_delta.chunks_before == 2
    assert trace.compression_delta.chunks_after == 1


def test_assemble_trace_no_compression_delta_when_missing() -> None:
    state = _make_state(compression_tokens_before=None)
    trace = _assemble_trace(state)
    assert trace.compression_delta is None


def test_assemble_trace_governance_summary() -> None:
    state = _make_state(
        governance_findings=[{"redacted": True}, {"redacted": False}],
        opa_denied_count=3,
        opa_bundle_version="v2.0",
        governance_blocked=True,
    )
    trace = _assemble_trace(state)

    assert trace.governance_decisions.findings_count == 2
    assert trace.governance_decisions.redacted_count == 1
    assert trace.governance_decisions.opa_denied_count == 3
    assert trace.governance_decisions.opa_bundle_version == "v2.0"
    assert trace.governance_decisions.governance_blocked is True


def test_assemble_trace_execution_plan_steps() -> None:
    state = _make_state(
        execution_trace=[
            {"node": "intent_agent", "eval_ms": 12.3},
            {"node": "retrieval_agent", "eval_ms": 88.0, "chunks": 5},
        ]
    )
    trace = _assemble_trace(state)

    assert len(trace.execution_plan) == 2
    assert trace.execution_plan[0].node == "intent_agent"
    assert trace.execution_plan[1].node == "retrieval_agent"
    assert trace.execution_plan[1].metadata == {"chunks": 5}


def test_assemble_trace_anonymous_user_when_no_claims() -> None:
    state = _make_state(jwt_claims=None)
    trace = _assemble_trace(state)
    assert trace.user_id == "anonymous"


def test_assemble_trace_response_truncated_at_500() -> None:
    long_response = "x" * 600
    state = _make_state(response=long_response)
    trace = _assemble_trace(state)
    assert trace.response_summary == "x" * 500


def test_assemble_trace_uses_existing_request_id_uuid() -> None:
    fixed_id = uuid.uuid4()
    state = _make_state(request_id=fixed_id)
    trace = _assemble_trace(state)
    assert trace.request_id == fixed_id


def test_assemble_trace_parses_string_request_id() -> None:
    fixed_id = uuid.uuid4()
    state = _make_state(request_id=str(fixed_id))
    trace = _assemble_trace(state)
    assert trace.request_id == fixed_id


def test_assemble_trace_prefers_current_pipeline_fields() -> None:
    state = _make_state(
        user_id="user-current",
        prompt="Why did context_query return 500?",
        intent_type=IntentType.DEBUGGING,
        selected_model="gpt-4.1-mini",
        query=None,
        intent=None,
        model_selected=None,
        response=None,
        final_response={
            "answer": "The request failed before graph serialization completed.",
            "selected_model": "gpt-4.1-mini",
            "usage": {"input_tokens": 456, "output_tokens": 123},
        },
        timestamp="2026-08-02T10:15:30Z",
    )

    trace = _assemble_trace(state)

    assert trace.user_id == "user-current"
    assert trace.prompt == "Why did context_query return 500?"
    assert trace.intent == "debugging"
    assert trace.model_selected == "gpt-4.1-mini"
    assert trace.prompt_tokens == 456
    assert trace.completion_tokens == 123
    assert trace.response_summary == "The request failed before graph serialization completed."
    assert trace.timestamp == datetime(2026, 8, 2, 10, 15, 30, tzinfo=UTC)


# ------------------------------------------------------------------ #
# trace_writer_node — AC-6 timing + state fields                      #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_trace_writer_node_returns_quickly() -> None:
    """trace_writer_node must complete in < 5 ms (AC-6)."""
    mock_store = AsyncMock()
    mock_store.write.return_value = _make_write_result()
    set_trace_object_store(mock_store)

    state = _make_state()

    with patch("src.audit.trace.writer_node.asyncio.create_task") as mock_create_task:
        mock_create_task.return_value = MagicMock()
        with patch("src.audit.trace.writer_node.langfuse"):
            start = time.monotonic()
            await trace_writer_node(state)
            elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 5.0, f"trace_writer_node took {elapsed_ms:.1f} ms (must be < 5 ms)"
    assert mock_create_task.called


@pytest.mark.asyncio
async def test_trace_writer_node_sets_state_fields() -> None:
    state = _make_state()

    with patch("src.audit.trace.writer_node.asyncio.create_task") as mock_create_task:
        mock_create_task.return_value = MagicMock()
        with patch("src.audit.trace.writer_node.langfuse"):
            result = await trace_writer_node(state)

    assert result["trace_written"] is True
    assert result["trace_id"] is not None
    assert uuid.UUID(result["trace_id"])  # valid UUID string
    assert result["trace_object_key"] is not None
    assert result["trace_object_key"].startswith("traces/")


@pytest.mark.asyncio
async def test_trace_writer_node_dispatches_background_task() -> None:
    state = _make_state()
    captured_coro = None

    def capture_task(coro: object, *, name: str | None = None) -> MagicMock:
        nonlocal captured_coro
        captured_coro = coro
        # Return a dummy task-like object
        task = MagicMock()
        return task

    with patch("src.audit.trace.writer_node.asyncio.create_task", side_effect=capture_task):
        with patch("src.audit.trace.writer_node.langfuse"):
            await trace_writer_node(state)

    assert captured_coro is not None
    # Clean up the unawaited coroutine
    captured_coro.close()


# ------------------------------------------------------------------ #
# _persist_trace — AC-6 exception swallowing                          #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_persist_trace_calls_store_then_repo() -> None:
    mock_store = AsyncMock()
    mock_store.write.return_value = _make_write_result()

    mock_session = AsyncMock()
    mock_repo = AsyncMock()

    @asynccontextmanager
    async def _session_ctx() -> AsyncMock:  # type: ignore[misc]
        yield mock_session

    state = _make_state(
        _config={
            "trace_object_store": mock_store,
            "trace_session_factory": _session_ctx,
        }
    )

    trace_obj = _assemble_trace(state)

    with patch("src.audit.trace.writer_node.TraceIndexRepository", return_value=mock_repo):
        await _persist_trace(trace_obj, state)

    mock_store.write.assert_awaited_once_with(trace_obj)
    mock_repo.upsert.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_trace_swallows_store_exception() -> None:
    """An exception from MinIO write must NOT propagate (AC-6)."""
    mock_store = AsyncMock()
    mock_store.write.side_effect = ConnectionError("MinIO unreachable")

    state = _make_state(_config={"trace_object_store": mock_store})
    trace_obj = _assemble_trace(state)

    # Should complete without raising
    await _persist_trace(trace_obj, state)


@pytest.mark.asyncio
async def test_persist_trace_swallows_db_exception() -> None:
    """An exception from PostgreSQL upsert must NOT propagate (AC-6)."""
    mock_store = AsyncMock()
    mock_store.write.return_value = _make_write_result()

    @asynccontextmanager
    async def _broken_session() -> None:  # type: ignore[misc]
        raise RuntimeError("DB connection lost")
        yield

    state = _make_state(
        _config={
            "trace_object_store": mock_store,
            "trace_session_factory": _broken_session,
        }
    )
    trace_obj = _assemble_trace(state)

    # Should complete without raising
    await _persist_trace(trace_obj, state)


# ------------------------------------------------------------------ #
# Singleton injection helpers                                          #
# ------------------------------------------------------------------ #


def test_set_trace_object_store_updates_default() -> None:
    mock_store = MagicMock()
    set_trace_object_store(mock_store)
    assert _mod._DEFAULT_OBJECT_STORE is mock_store


def test_set_trace_session_factory_updates_default() -> None:
    mock_factory = MagicMock()
    set_trace_session_factory(mock_factory)
    assert _mod._DEFAULT_SESSION_FACTORY is mock_factory


def test_get_object_store_prefers_config_over_default() -> None:
    config_store = MagicMock()
    default_store = MagicMock()
    set_trace_object_store(default_store)

    state = _make_state(_config={"trace_object_store": config_store})
    from src.audit.trace.writer_node import _get_object_store
    assert _get_object_store(state) is config_store


def test_get_object_store_falls_back_to_default() -> None:
    default_store = MagicMock()
    set_trace_object_store(default_store)

    state = _make_state(_config={})
    from src.audit.trace.writer_node import _get_object_store
    assert _get_object_store(state) is default_store
