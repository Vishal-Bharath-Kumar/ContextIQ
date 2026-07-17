"""governance_node — mandatory LangGraph governance gate (TASK-US031-04).

Position: after knowledge_graph node, before compression/routing node.

Runs SecretPIIDetector and ContextRedactor over ranked_context, records all
findings in the execution_trace (AC-7), emits OTel span and Langfuse event,
and returns updated AgentState.  On scan timeout the node activates the
fail-safe: ranked_context is emptied so no unscanned content reaches the LLM.
"""

from __future__ import annotations

import logging

from langfuse import Langfuse
from opentelemetry import trace

from src.agents.state import AgentState, ExecutionStatus
from src.governance.detection.detector import (
    GovernanceScanTimeoutError,
    SecretPIIDetector,
)
from src.governance.detection.redactor import ContextRedactor
from src.governance.schemas.finding import DetectionFinding
from src.observability.tracing.node_span import otel_node_span

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Module-level singletons — no per-request state; safe to share across calls.
_DETECTOR = SecretPIIDetector()
_REDACTOR = ContextRedactor()
_langfuse = Langfuse()


@otel_node_span("governance.pii_scan")
async def governance_node(state: AgentState) -> dict:
    """Mandatory LangGraph node — Governance Gate.

    Steps:
    1. Run SecretPIIDetector.scan_context() over ranked_context.
    2. On timeout → set governance_blocked=True, return empty ranked_context
       (fail-safe: no unscanned content reaches the LLM).
    3. Run ContextRedactor.redact_context() for critical/high findings.
    4. Record all findings in execution_trace (AC-7).
    5. Emit OTel span and Langfuse event.
    6. Return updated fields for AgentState.

    The scanning logic is CPU-bound (regex, no I/O) and completes in < 200 ms.
    """
    ranked_context: list[dict] = state.get("ranked_context") or []

    with tracer.start_as_current_span("governance.scan") as span:
        span.set_attribute("governance.chunks_count", len(ranked_context))

        # ── 1. Scan ────────────────────────────────────────────────────
        try:
            scan_result = _DETECTOR.scan_context(ranked_context)
        except GovernanceScanTimeoutError as exc:
            logger.error(
                "governance_node: scan timeout — blocking context from LLM. error=%s",
                exc,
            )
            span.set_attribute("governance.blocked", True)
            span.set_attribute("governance.timeout", True)
            _append_trace_entry(state, findings=[], scan_ms=0.0, blocked=True)
            return {
                "current_node": "governance_agent",
                "status": ExecutionStatus.RUNNING,
                "ranked_context": [],  # fail-safe: empty, not unscanned
                "governance_findings": [],
                "context_redacted": False,
                "governance_scan_ms": 0.0,
                "governance_blocked": True,
                "execution_trace": _build_trace(state, findings=[], scan_ms=0.0, blocked=True),
            }

        findings: list[DetectionFinding] = scan_result.findings
        scan_ms: float = scan_result.scan_duration_ms

        span.set_attribute("governance.findings_count", len(findings))
        span.set_attribute("governance.has_critical_or_high", scan_result.has_critical_or_high)
        span.set_attribute("governance.scan_ms", scan_ms)

        # ── 2. Redact critical/high findings ──────────────────────────
        if scan_result.has_critical_or_high:
            updated_context, _ = _REDACTOR.redact_context(ranked_context, scan_result)
            context_redacted = True
        else:
            updated_context = ranked_context
            context_redacted = False

        # ── 3. Langfuse event ─────────────────────────────────────────
        try:
            _langfuse.create_event(
                name="governance_scan",
                input={"chunks_scanned": scan_result.chunks_scanned},
                output={
                    "findings_count": len(findings),
                    "redacted": context_redacted,
                    "scan_ms": scan_ms,
                },
                metadata={
                    "critical_or_high": scan_result.has_critical_or_high,
                    "pattern_types": list({f.pattern_type.value for f in findings}),
                },
            )
        except Exception as lf_exc:  # pragma: no cover — Langfuse I/O failure is non-fatal
            logger.warning("governance_node: langfuse event failed: %s", lf_exc)

        if findings:
            logger.warning(
                "governance_node: %d finding(s) detected, redacted=%s. Types: %s",
                len(findings),
                context_redacted,
                {f.pattern_type.value for f in findings},
            )

        return {
            "current_node": "governance_agent",
            "status": ExecutionStatus.RUNNING,
            "ranked_context": updated_context,
            "governance_findings": findings,
            "context_redacted": context_redacted,
            "governance_scan_ms": scan_ms,
            "governance_blocked": False,
            "execution_trace": _build_trace(state, findings=findings, scan_ms=scan_ms, blocked=False),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_trace(
    state: AgentState,
    findings: list[DetectionFinding],
    scan_ms: float,
    blocked: bool,
) -> list[dict]:
    """Return an updated execution_trace list with a new governance entry appended.

    The trace entry is dict-serialisable for downstream audit storage (EP-011).
    Never mutates the existing list — returns a new list.
    """
    trace_entry: dict = {
        "node": "governance",
        "scan_ms": scan_ms,
        "blocked": blocked,
        "findings": [
            {
                "pattern_type": f.pattern_type.value,
                "severity": f.severity.value,
                "chunk_id": f.chunk_id,
                "char_offset": f.char_offset,
                "preview": f.match_preview,
            }
            for f in findings
        ],
    }
    existing: list[dict] = state.get("execution_trace") or []
    return existing + [trace_entry]


def _append_trace_entry(
    state: AgentState,
    findings: list[DetectionFinding],
    scan_ms: float,
    blocked: bool,
) -> None:
    """No-op helper kept for symmetry; actual trace update is returned in the state dict."""
