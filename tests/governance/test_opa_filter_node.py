"""Unit tests for opa_filter_node() — TASK-US032-04.

Covers all acceptance criteria:
  AC-2:  ChunkAuthzInput built with all four required fields per chunk
  AC-3:  Denied chunks absent from returned ranked_context; allowed preserved in order
  AC-4:  execution_trace contains an "opa_filter" entry with per-chunk decisions
  AC-7:  governance_policy_denials_total incremented for each denied chunk
  Early-exit: empty ranked_context returns immediately without calling OPAClient
  Fail-safe: OPAEvaluationError propagates (no silent allow)

OPAClient is injected via state["_config"]["opa_client"] — no live OPA in CI.
OTel tracer and Langfuse are replaced with stubs.
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.governance.opa.client import OPAEvaluationError
from src.governance.opa.schemas import AuthzFilterResult, PolicyDecision
from src.governance.nodes.opa_filter_node import opa_filter_node

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(
    chunk_id: str,
    allow: bool,
    rationale: str = "",
    eval_ms: float = 2.0,
) -> PolicyDecision:
    return PolicyDecision(
        chunk_id=chunk_id,
        allow=allow,
        rationale=rationale,
        eval_ms=eval_ms,
    )


def _make_filter_result(
    decisions: list[PolicyDecision],
    bundle_version: str = "test-v1",
    total_eval_ms: float = 10.0,
) -> AuthzFilterResult:
    allowed = [d.chunk_id for d in decisions if d.allow]
    denied = [d.chunk_id for d in decisions if not d.allow]
    return AuthzFilterResult(
        decisions=decisions,
        allowed_chunk_ids=allowed,
        denied_chunk_ids=denied,
        total_eval_ms=total_eval_ms,
        bundle_version=bundle_version,
    )


def _make_chunk(chunk_id: str, classification: str = "internal") -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": "src-001",
        "document_id": "doc-001",
        "text": f"content of {chunk_id}",
        "metadata": {"classification_label": classification},
    }


def _base_state(**overrides: object) -> dict:
    base: dict = {
        "request_id": "req-test-001",
        "user_id": "user-abc",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "test_tool",
        "prompt": "test",
        "timestamp": "2026-07-17T00:00:00Z",
        "status": "running",
        "current_node": "opa_filter",
        "error": None,
        "ranked_context": [],
        "execution_trace": None,
        "jwt_claims": {"realm_access": {"roles": ["developer"]}},
        "tenant_id": "tenant-xyz",
    }
    base.update(overrides)
    return base


def _mock_opa_client(filter_result: AuthzFilterResult) -> MagicMock:
    client = MagicMock()
    client.evaluate_batch = AsyncMock(return_value=filter_result)
    return client


@contextmanager
def _noop_span(*args: object, **kwargs: object) -> Generator[MagicMock, None, None]:
    span = MagicMock()
    yield span


def _make_tracer_mock() -> MagicMock:
    tracer = MagicMock()
    tracer.start_as_current_span.side_effect = _noop_span
    return tracer


def _state_with_client(client: object, **overrides: object) -> dict:
    state = _base_state(**overrides)
    state["_config"] = {"opa_client": client}
    return state


# ---------------------------------------------------------------------------
# AC-3 / AC-4 / AC-7: allow + deny mix
# ---------------------------------------------------------------------------


async def test_denied_chunks_filtered_from_ranked_context() -> None:
    """AC-3: denied chunks absent from returned ranked_context."""
    chunks = [_make_chunk("chunk-1"), _make_chunk("chunk-2"), _make_chunk("chunk-3")]
    decisions = [
        _make_decision("chunk-1", allow=True),
        _make_decision("chunk-2", allow=False, rationale="restricted classification"),
        _make_decision("chunk-3", allow=True),
    ]
    result = _make_filter_result(decisions)
    client = _mock_opa_client(result)

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        out = await opa_filter_node(_state_with_client(client, ranked_context=chunks))  # type: ignore[arg-type]

    remaining_ids = [c["chunk_id"] for c in out["ranked_context"]]
    assert "chunk-2" not in remaining_ids
    assert remaining_ids == ["chunk-1", "chunk-3"]


async def test_allowed_chunks_preserved_in_original_order() -> None:
    """AC-3: allowed chunks are present and in their original order."""
    chunks = [_make_chunk(f"chunk-{i}") for i in range(5)]
    decisions = [_make_decision(f"chunk-{i}", allow=True) for i in range(5)]
    result = _make_filter_result(decisions)
    client = _mock_opa_client(result)

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        out = await opa_filter_node(_state_with_client(client, ranked_context=chunks))  # type: ignore[arg-type]

    assert [c["chunk_id"] for c in out["ranked_context"]] == [f"chunk-{i}" for i in range(5)]


async def test_execution_trace_contains_opa_filter_entry() -> None:
    """AC-4: execution_trace has an 'opa_filter' entry with per-chunk decisions."""
    chunks = [_make_chunk("chunk-1"), _make_chunk("chunk-2")]
    decisions = [
        _make_decision("chunk-1", allow=True),
        _make_decision("chunk-2", allow=False, rationale="tenant policy"),
    ]
    result = _make_filter_result(decisions, total_eval_ms=8.5)
    client = _mock_opa_client(result)

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        out = await opa_filter_node(_state_with_client(client, ranked_context=chunks))  # type: ignore[arg-type]

    trace: list[dict] = out["execution_trace"]
    assert len(trace) == 1
    entry = trace[0]
    assert entry["node"] == "opa_filter"
    assert entry["eval_ms"] == 8.5
    assert len(entry["decisions"]) == 2
    deny_entry = next(d for d in entry["decisions"] if d["chunk_id"] == "chunk-2")
    assert deny_entry["allow"] is False
    assert deny_entry["rationale"] == "tenant policy"


async def test_execution_trace_appended_to_existing_trace() -> None:
    """AC-4: existing entries in execution_trace are preserved."""
    existing = [{"node": "governance", "eval_ms": 5.0, "decisions": []}]
    chunks = [_make_chunk("chunk-1")]
    decisions = [_make_decision("chunk-1", allow=True)]
    result = _make_filter_result(decisions)
    client = _mock_opa_client(result)

    state = _state_with_client(client, ranked_context=chunks, execution_trace=existing)
    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        out = await opa_filter_node(state)  # type: ignore[arg-type]

    assert out["execution_trace"][0]["node"] == "governance"
    assert out["execution_trace"][1]["node"] == "opa_filter"


async def test_denials_counter_incremented(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-7: governance_policy_denials_total incremented for each denied chunk."""
    import src.governance.opa.metrics as metrics_module

    denial_counter = MagicMock()
    monkeypatch.setattr(
        "src.governance.nodes.opa_filter_node.governance_policy_denials_total",
        denial_counter,
    )

    chunks = [
        _make_chunk("chunk-1", classification="confidential"),
        _make_chunk("chunk-2", classification="internal"),
    ]
    decisions = [
        _make_decision("chunk-1", allow=False),
        _make_decision("chunk-2", allow=False),
    ]
    result = _make_filter_result(decisions)
    client = _mock_opa_client(result)

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        await opa_filter_node(_state_with_client(client, ranked_context=chunks))  # type: ignore[arg-type]

    assert denial_counter.labels.call_count == 2
    calls = [c.kwargs for c in denial_counter.labels.call_args_list]
    labels = {(c["tenant_id"], c["classification_label"]) for c in calls}
    assert ("tenant-xyz", "confidential") in labels
    assert ("tenant-xyz", "internal") in labels


# ---------------------------------------------------------------------------
# AC-2: ChunkAuthzInput built correctly
# ---------------------------------------------------------------------------


async def test_chunk_authz_input_contains_required_fields() -> None:
    """AC-2: all four required fields present in each ChunkAuthzInput passed to OPA."""
    chunks = [_make_chunk("chunk-1")]
    decisions = [_make_decision("chunk-1", allow=True)]
    result = _make_filter_result(decisions)
    client = _mock_opa_client(result)

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        await opa_filter_node(_state_with_client(client, ranked_context=chunks))  # type: ignore[arg-type]

    client.evaluate_batch.assert_awaited_once()
    sent_inputs = client.evaluate_batch.call_args.args[0]
    assert len(sent_inputs) == 1
    inp = sent_inputs[0]
    assert inp.user_roles == ["developer"]
    assert inp.tenant_id == "tenant-xyz"
    assert inp.source_id == "src-001"
    assert inp.classification_label == "internal"


# ---------------------------------------------------------------------------
# Empty ranked_context — early exit, OPAClient not called
# ---------------------------------------------------------------------------


async def test_empty_ranked_context_returns_immediately() -> None:
    """Empty ranked_context returns immediately without calling OPAClient."""
    client = MagicMock()
    client.evaluate_batch = AsyncMock()

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        out = await opa_filter_node(_state_with_client(client, ranked_context=[]))  # type: ignore[arg-type]

    client.evaluate_batch.assert_not_awaited()
    assert out["opa_decisions"] == []
    assert out["opa_denied_count"] == 0


# ---------------------------------------------------------------------------
# Fail-safe: OPAEvaluationError propagates
# ---------------------------------------------------------------------------


async def test_opa_evaluation_error_propagates() -> None:
    """OPAEvaluationError propagates to the caller — no silent allow."""
    client = MagicMock()
    client.evaluate_batch = AsyncMock(side_effect=OPAEvaluationError("OPA sidecar down"))

    chunks = [_make_chunk("chunk-1")]
    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
        pytest.raises(OPAEvaluationError),
    ):
        await opa_filter_node(_state_with_client(client, ranked_context=chunks))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fail-safe: missing OPAClient raises OPAEvaluationError
# ---------------------------------------------------------------------------


async def test_missing_opa_client_raises() -> None:
    """If no OPAClient is configured, OPAEvaluationError is raised (fail-safe)."""
    state = _base_state(ranked_context=[_make_chunk("chunk-1")])
    # No "_config" key → _DEFAULT_OPA_CLIENT is None

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
        patch("src.governance.nodes.opa_filter_node._DEFAULT_OPA_CLIENT", None),
        pytest.raises(OPAEvaluationError),
    ):
        await opa_filter_node(state)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Role extraction — fallback to state["roles"]
# ---------------------------------------------------------------------------


async def test_roles_fall_back_to_state_roles_when_no_jwt_claims() -> None:
    """_extract_user_roles uses state['roles'] when jwt_claims is absent."""
    chunks = [_make_chunk("chunk-1")]
    decisions = [_make_decision("chunk-1", allow=True)]
    result = _make_filter_result(decisions)
    client = _mock_opa_client(result)

    state = _state_with_client(client, ranked_context=chunks)
    del state["jwt_claims"]  # remove jwt_claims

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        await opa_filter_node(state)  # type: ignore[arg-type]

    sent_inputs = client.evaluate_batch.call_args.args[0]
    assert sent_inputs[0].user_roles == ["developer"]


# ---------------------------------------------------------------------------
# State output fields
# ---------------------------------------------------------------------------


async def test_output_state_contains_opa_fields() -> None:
    """Returned state contains opa_decisions, opa_denied_count, opa_bundle_version."""
    chunks = [_make_chunk("chunk-1")]
    decisions = [_make_decision("chunk-1", allow=True)]
    result = _make_filter_result(decisions, bundle_version="v2.0.1")
    client = _mock_opa_client(result)

    # Inject a hot_reloader stub so bundle_version is deterministic.
    bundle_stub = MagicMock()
    bundle_stub.current_bundle.version = "v2.0.1"
    state = _state_with_client(client, ranked_context=chunks)
    state["_config"]["hot_reloader"] = bundle_stub

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        out = await opa_filter_node(state)  # type: ignore[arg-type]

    assert out["opa_denied_count"] == 0
    assert out["opa_bundle_version"] == "v2.0.1"
    assert len(out["opa_decisions"]) == 1


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-3: denied chunks filtered (named per acceptance criteria)
# Injects OPA client via set_opa_client() using conftest fixtures.
# ---------------------------------------------------------------------------

async def test_denied_chunks_filtered(two_item_context, mock_opa_deny_restricted) -> None:
    """AC-3: chunk with classification_label='restricted' is absent from ranked_context."""
    from tests.governance.conftest import TENANT_ID, USER_ROLES
    from src.governance.nodes.opa_filter_node import set_opa_client

    set_opa_client(mock_opa_deny_restricted)
    state = _base_state(
        ranked_context=two_item_context,
        jwt_claims={"roles": USER_ROLES},
        tenant_id=TENANT_ID,
    )

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        result = await opa_filter_node(state)  # type: ignore[arg-type]

    # CHUNK_A is "internal" → allowed; CHUNK_B is "restricted" → denied
    chunk_a_id = two_item_context[0]["chunk_id"]
    assert len(result["ranked_context"]) == 1
    assert result["ranked_context"][0]["chunk_id"] == chunk_a_id
    assert result["opa_denied_count"] == 1


async def test_allowed_chunks_preserved_in_order(two_item_context, mock_opa_allow_all) -> None:
    """AC-3: when all chunks are allowed, both are returned in original order."""
    from tests.governance.conftest import TENANT_ID, USER_ROLES
    from src.governance.nodes.opa_filter_node import set_opa_client

    set_opa_client(mock_opa_allow_all)
    state = _base_state(
        ranked_context=two_item_context,
        jwt_claims={"roles": USER_ROLES},
        tenant_id=TENANT_ID,
    )

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        result = await opa_filter_node(state)  # type: ignore[arg-type]

    assert len(result["ranked_context"]) == 2
    assert result["ranked_context"][0]["chunk_id"] == two_item_context[0]["chunk_id"]
    assert result["ranked_context"][1]["chunk_id"] == two_item_context[1]["chunk_id"]


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-4: policy decision recorded in execution trace (named per AC)
# ---------------------------------------------------------------------------

async def test_decisions_recorded_in_execution_trace(
    two_item_context, mock_opa_deny_restricted
) -> None:
    """AC-4: execution_trace contains an 'opa_filter' entry with all decisions;
    denied chunk has a non-empty rationale."""
    from tests.governance.conftest import TENANT_ID, USER_ROLES
    from src.governance.nodes.opa_filter_node import set_opa_client

    set_opa_client(mock_opa_deny_restricted)
    state = _base_state(
        ranked_context=two_item_context,
        jwt_claims={"roles": USER_ROLES},
        tenant_id=TENANT_ID,
    )

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        result = await opa_filter_node(state)  # type: ignore[arg-type]

    trace = result.get("execution_trace") or []
    opa_entry = next((e for e in trace if e.get("node") == "opa_filter"), None)
    assert opa_entry is not None

    decisions = opa_entry["decisions"]
    assert len(decisions) == 2

    # CHUNK_B is the "restricted" chunk — should be denied with a non-empty rationale
    chunk_b_id = two_item_context[1]["chunk_id"]
    denied = [d for d in decisions if not d["allow"]]
    assert len(denied) == 1
    assert denied[0]["chunk_id"] == chunk_b_id
    assert "rationale" in denied[0]
    assert denied[0]["rationale"] != ""


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-7: governance_policy_denials_total incremented (named per AC)
# ---------------------------------------------------------------------------

async def test_governance_policy_denials_total_incremented(
    two_item_context, mock_opa_deny_restricted
) -> None:
    """AC-7: governance_policy_denials_total incremented by 1 for the denied chunk.

    Uses scoped ._value.get() on the specific label combination — not a global reset.
    """
    from tests.governance.conftest import TENANT_ID, USER_ROLES
    from src.governance.nodes.opa_filter_node import set_opa_client
    from src.governance.opa.metrics import governance_policy_denials_total

    set_opa_client(mock_opa_deny_restricted)

    before = governance_policy_denials_total.labels(
        tenant_id=TENANT_ID, classification_label="restricted"
    )._value.get()

    state = _base_state(
        ranked_context=two_item_context,
        jwt_claims={"roles": USER_ROLES},
        tenant_id=TENANT_ID,
    )

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        await opa_filter_node(state)  # type: ignore[arg-type]

    after = governance_policy_denials_total.labels(
        tenant_id=TENANT_ID, classification_label="restricted"
    )._value.get()
    assert after - before == 1


async def test_no_denials_counter_not_incremented(
    two_item_context, mock_opa_allow_all
) -> None:
    """AC-7: when all chunks are allowed, governance_policy_denials_total is unchanged."""
    from tests.governance.conftest import TENANT_ID, USER_ROLES
    from src.governance.nodes.opa_filter_node import set_opa_client
    from src.governance.opa.metrics import governance_policy_denials_total

    set_opa_client(mock_opa_allow_all)

    before = sum(
        s._value.get() for s in governance_policy_denials_total._metrics.values()
    )

    state = _base_state(
        ranked_context=two_item_context,
        jwt_claims={"roles": ["admin"]},
        tenant_id=TENANT_ID,
    )

    with (
        patch("src.governance.nodes.opa_filter_node.tracer", _make_tracer_mock()),
        patch("src.governance.nodes.opa_filter_node._langfuse", MagicMock()),
    ):
        await opa_filter_node(state)  # type: ignore[arg-type]

    after = sum(
        s._value.get() for s in governance_policy_denials_total._metrics.values()
    )
    assert after == before
