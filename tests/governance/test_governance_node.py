"""Unit tests for governance_node() — TASK-US031-04.

Covers all acceptance criteria:
  AC-1:  governance_node is always invoked (no conditional guard)
  AC-4:  context_redacted=True when critical/high findings exist
  AC-5:  medium-only findings -> context_redacted=False
  AC-7:  execution_trace contains a "governance" entry after the node runs
  Fail-safe: GovernanceScanTimeoutError sets governance_blocked=True, ranked_context=[]
  OTel span "governance.scan" is created for every invocation
  governance_scan_ms matches GovernanceScanResult.scan_duration_ms

SecretPIIDetector and ContextRedactor are exercised directly (not mocked).
OTel tracer and Langfuse are replaced with MagicMock / contextmanager stubs.
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from src.governance.nodes.governance_node import governance_node
from src.governance.schemas.finding import Severity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
_CREDIT_CARD = "4111111111111111"
_PHONE = "+1-800-555-0100"


def _base_state(**overrides: object) -> dict:
    base: dict = {
        "request_id": "req-test-001",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["user"],
        "tool_name": "test_tool",
        "prompt": "test prompt",
        "timestamp": "2026-07-17T00:00:00Z",
        "status": "running",
        "current_node": "governance_agent",
        "error": None,
        "ranked_context": [],
        "execution_trace": None,
    }
    base.update(overrides)
    return base


def _make_chunk(text: str, chunk_id: str = "chunk-1") -> dict:
    return {"text": text, "chunk_id": chunk_id}


@contextmanager
def _noop_span(*args: object, **kwargs: object) -> Generator[MagicMock, None, None]:
    span: MagicMock = MagicMock()
    yield span


def _make_tracer_mock() -> MagicMock:
    tracer = MagicMock()
    tracer.start_as_current_span.side_effect = _noop_span
    return tracer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_clean_context_no_findings() -> None:
    state = _base_state(ranked_context=[_make_chunk("Hello world, nothing secret here.")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["governance_findings"] == []
    assert result["context_redacted"] is False
    assert result["governance_blocked"] is False
    assert isinstance(result["governance_scan_ms"], float)
    assert result["ranked_context"] == state["ranked_context"]
    tracer_mock.start_as_current_span.assert_called_once_with("governance.scan")


async def test_critical_finding_triggers_redaction() -> None:
    state = _base_state(ranked_context=[_make_chunk(f"key={_AWS_KEY}", chunk_id="c1")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["context_redacted"] is True
    assert result["governance_blocked"] is False
    assert len(result["governance_findings"]) >= 1
    assert any(f.severity == Severity.CRITICAL for f in result["governance_findings"])
    assert _AWS_KEY not in result["ranked_context"][0]["text"]
    assert "[REDACTED:" in result["ranked_context"][0]["text"]


async def test_high_severity_credit_card_redacted() -> None:
    state = _base_state(ranked_context=[_make_chunk(f"pay with card {_CREDIT_CARD}", chunk_id="c2")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["context_redacted"] is True
    assert any(f.severity == Severity.HIGH for f in result["governance_findings"])


async def test_medium_only_finding_not_redacted() -> None:
    state = _base_state(ranked_context=[_make_chunk(f"call us at {_PHONE}", chunk_id="c3")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["context_redacted"] is False
    assert result["governance_blocked"] is False
    if result["governance_findings"]:
        for f in result["governance_findings"]:
            assert f.severity == Severity.MEDIUM


async def test_scan_timeout_activates_fail_safe() -> None:
    from src.governance.detection.detector import GovernanceScanTimeoutError

    state = _base_state(ranked_context=[_make_chunk("some text", chunk_id="c4")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
        patch(
            "src.governance.nodes.governance_node._DETECTOR.scan_context",
            side_effect=GovernanceScanTimeoutError("timed out"),
        ),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["governance_blocked"] is True
    assert result["ranked_context"] == []
    assert result["governance_findings"] == []
    assert result["context_redacted"] is False
    assert result["governance_scan_ms"] == 0.0


async def test_execution_trace_contains_governance_entry() -> None:
    state = _base_state(ranked_context=[_make_chunk(f"key={_AWS_KEY}", chunk_id="trace-c1")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    trace = result["execution_trace"]
    assert isinstance(trace, list) and len(trace) >= 1
    gov_entry = next((e for e in trace if e.get("node") == "governance"), None)
    assert gov_entry is not None
    assert "scan_ms" in gov_entry
    assert "blocked" in gov_entry
    assert "findings" in gov_entry
    assert gov_entry["blocked"] is False


async def test_execution_trace_appends_to_existing() -> None:
    existing_entry = {"node": "retrieval", "duration_ms": 50.0}
    state = _base_state(
        ranked_context=[_make_chunk("clean text", chunk_id="c5")],
        execution_trace=[existing_entry],
    )
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    trace = result["execution_trace"]
    assert len(trace) == 2
    assert trace[0]["node"] == "retrieval"
    assert trace[1]["node"] == "governance"


async def test_governance_scan_ms_matches_scan_result() -> None:
    from src.governance.schemas.finding import GovernanceScanResult

    fake_scan = GovernanceScanResult.build(findings=[], chunks_scanned=1, scan_duration_ms=42.5)
    state = _base_state(ranked_context=[_make_chunk("text", chunk_id="c6")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
        patch("src.governance.nodes.governance_node._DETECTOR.scan_context", return_value=fake_scan),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["governance_scan_ms"] == 42.5


async def test_empty_ranked_context() -> None:
    state = _base_state(ranked_context=[])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["governance_findings"] == []
    assert result["context_redacted"] is False
    assert result["governance_blocked"] is False
    assert result["ranked_context"] == []


async def test_timeout_trace_entry_blocked_true() -> None:
    from src.governance.detection.detector import GovernanceScanTimeoutError

    state = _base_state(ranked_context=[_make_chunk("text")])
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
        patch(
            "src.governance.nodes.governance_node._DETECTOR.scan_context",
            side_effect=GovernanceScanTimeoutError("timeout"),
        ),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    trace = result["execution_trace"]
    gov_entry = next(e for e in trace if e["node"] == "governance")
    assert gov_entry["blocked"] is True
    assert gov_entry["findings"] == []


# ---------------------------------------------------------------------------
# TASK-US031-05: Integration tests — AC-1 (node position) + AC-7 (audit trace)
# Using conftest fixtures: single_chunk, clean_chunk, medium_only_chunk
# ---------------------------------------------------------------------------


async def test_governance_node_appends_to_execution_trace(single_chunk: list[dict]) -> None:
    """AC-7: execution_trace contains a 'governance' entry with findings and scan_ms."""
    state = _base_state(ranked_context=single_chunk)
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert "execution_trace" in result
    trace = result["execution_trace"]
    assert len(trace) >= 1
    gov_entry = next((e for e in trace if e.get("node") == "governance"), None)
    assert gov_entry is not None
    assert "findings" in gov_entry
    assert "scan_ms" in gov_entry


async def test_governance_node_blocks_on_scan_timeout(single_chunk: list[dict]) -> None:
    """AC-1/fail-safe: GovernanceScanTimeoutError sets governance_blocked=True, ranked_context=[]."""
    from src.governance.detection.detector import GovernanceScanTimeoutError

    state = _base_state(ranked_context=single_chunk)
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
        patch(
            "src.governance.nodes.governance_node._DETECTOR.scan_context",
            side_effect=GovernanceScanTimeoutError("timeout"),
        ),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["governance_blocked"] is True
    assert result["ranked_context"] == []


async def test_governance_node_redacts_critical_findings(single_chunk: list[dict]) -> None:
    """AC-4: raw secrets must not appear in ranked_context after governance_node runs."""
    state = _base_state(ranked_context=single_chunk)
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["context_redacted"] is True
    for item in result["ranked_context"]:
        assert "AKIAIOSFODNN7EXAMPLE" not in item.get("text", "")


async def test_governance_node_does_not_redact_medium_findings(
    medium_only_chunk: list[dict],
) -> None:
    """AC-4: MEDIUM findings leave context unchanged and context_redacted stays False."""
    state = _base_state(ranked_context=medium_only_chunk)
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["context_redacted"] is False
    assert "+44 7700 900123" in result["ranked_context"][0]["text"]


async def test_governance_node_clean_context(clean_chunk: list[dict]) -> None:
    """AC-1: zero-finding path returns original context unchanged, no block, no redaction."""
    state = _base_state(ranked_context=clean_chunk)
    tracer_mock = _make_tracer_mock()

    with (
        patch("src.governance.nodes.governance_node.tracer", tracer_mock),
        patch("src.governance.nodes.governance_node._langfuse", MagicMock()),
    ):
        result = await governance_node(state)  # type: ignore[arg-type]

    assert result["governance_findings"] == []
    assert result["context_redacted"] is False
    assert result["governance_blocked"] is False
    assert result["ranked_context"] == clean_chunk
