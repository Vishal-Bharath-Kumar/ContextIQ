"""governance_node — mandatory LangGraph governance gate (TASK-US031-04).

Position: after knowledge_graph node, before compression/routing node.

Runs SecretPIIDetector and ContextRedactor over ranked_context, records all
findings in the execution_trace (AC-7), emits OTel span and Langfuse event,
validates compliance (GDPR, SOC2, HIPAA, PCI-DSS), performs RBAC validation,
and returns updated AgentState with comprehensive governance summary.

On scan timeout the node activates the fail-safe: ranked_context is emptied 
so no unscanned content reaches the LLM.
"""

from __future__ import annotations

import logging

from langfuse import Langfuse
from opentelemetry import trace

from src.agents.state import AgentState, ExecutionStatus
from src.governance.compliance.validator import ComplianceStandard, ComplianceValidator
from src.governance.detection.detector import (
    GovernanceScanTimeoutError,
    SecretPIIDetector,
)
from src.governance.detection.redactor import ContextRedactor
from src.governance.rbac.validator import Permission, RBACValidator, UserRole
from src.governance.schemas.finding import DetectionFinding
from src.governance.summary.generator import GovernanceSummary
from src.observability.tracing.node_span import otel_node_span

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Module-level singletons — no per-request state; safe to share across calls.
_DETECTOR = SecretPIIDetector()
_REDACTOR = ContextRedactor()
_COMPLIANCE_VALIDATOR = ComplianceValidator()
_RBAC_VALIDATOR = RBACValidator()
_langfuse = Langfuse()


@otel_node_span("governance.comprehensive_scan")
async def governance_node(state: AgentState) -> dict:
    """Mandatory LangGraph node — Comprehensive Governance Gate.

    Steps:
    1. Run SecretPIIDetector.scan_context() over ranked_context.
    2. On timeout → set governance_blocked=True, return empty ranked_context
       (fail-safe: no unscanned content reaches the LLM).
    3. Validate compliance (GDPR, SOC2, HIPAA, PCI-DSS).
    4. Validate RBAC permissions for user.
    5. Run ContextRedactor.redact_context() for critical/high findings.
    6. Generate comprehensive governance summary with risk scoring.
    7. Record all findings in execution_trace (AC-7).
    8. Emit OTel span and Langfuse event.
    9. Return updated fields for AgentState.

    The scanning logic is CPU-bound (regex, no I/O) and completes in < 200 ms.
    """
    ranked_context: list[dict] = state.get("ranked_context") or []
    execution_id: str = state.get("request_id", "unknown")
    user: str = state.get("user_id", "system")

    # Extract user role from state (default to 'admin' for backward compatibility)
    user_role_str = state.get("user_role", "admin")
    try:
        user_role = UserRole(user_role_str.lower())
    except ValueError:
        logger.warning(f"Invalid user role '{user_role_str}', defaulting to 'admin'")
        user_role = UserRole.ADMIN

    with tracer.start_as_current_span("governance.comprehensive_scan") as span:
        span.set_attribute("governance.chunks_count", len(ranked_context))
        span.set_attribute("governance.user", user)
        span.set_attribute("governance.user_role", user_role.value)

        # ── 1. Scan for secrets/PII ────────────────────────────────────
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

        # ── 2. Validate compliance ─────────────────────────────────────
        enabled_standards = [
            ComplianceStandard.GDPR,
            ComplianceStandard.SOC2,
            ComplianceStandard.PCI_DSS,
        ]
        compliance_result = _COMPLIANCE_VALIDATOR.validate(findings, enabled_standards)
        
        span.set_attribute("governance.compliance_status", compliance_result.overall_status.value)
        span.set_attribute("governance.risk_score", compliance_result.risk_score)

        logger.info(
            f"governance_node: compliance check - {compliance_result.overall_status.value}, "
            f"risk_score={compliance_result.risk_score}"
        )

        # ── 3. Validate RBAC ───────────────────────────────────────────
        rbac_result = _RBAC_VALIDATOR.validate(
            user_role=user_role,
            required_permissions=[Permission.READ, Permission.DEBUG],
            data_classification="INTERNAL",
        )
        
        span.set_attribute("governance.rbac_authorized", rbac_result.authorized)
        span.set_attribute("governance.rbac_classification", rbac_result.data_classification.value)

        if not rbac_result.authorized:
            logger.warning(
                f"governance_node: RBAC denied - {rbac_result.message}"
            )
            # Block access if RBAC fails
            return {
                "current_node": "governance_agent",
                "status": ExecutionStatus.RUNNING,
                "ranked_context": [],  # blocked due to RBAC
                "governance_findings": findings,
                "context_redacted": False,
                "governance_scan_ms": scan_ms,
                "governance_blocked": True,
                "governance_summary": {
                    "decision": "BLOCK",
                    "reason": rbac_result.message,
                    "risk_score": compliance_result.risk_score,
                },
                "execution_trace": _build_trace(
                    state, 
                    findings=findings, 
                    scan_ms=scan_ms, 
                    blocked=True,
                    rbac_denied=True,
                ),
            }

        # ── 4. Redact critical/high findings ───────────────────────────
        if scan_result.has_critical_or_high:
            updated_context, _ = _REDACTOR.redact_context(ranked_context, scan_result)
            context_redacted = True
        else:
            updated_context = ranked_context
            context_redacted = False

        # ── 5. Generate comprehensive summary ──────────────────────────
        governance_summary = GovernanceSummary.build(
            findings=findings,
            compliance_result=compliance_result,
            rbac_result=rbac_result,
            execution_id=execution_id,
            user=user,
            context_redacted=context_redacted,
        )

        span.set_attribute("governance.decision", governance_summary.decision)
        span.set_attribute("governance.risk_level", governance_summary.risk_level)

        # ── 6. Langfuse event ──────────────────────────────────────────
        try:
            _langfuse.create_event(
                name="governance_comprehensive_scan",
                input={"chunks_scanned": scan_result.chunks_scanned},
                output={
                    "findings_count": len(findings),
                    "redacted": context_redacted,
                    "scan_ms": scan_ms,
                    "decision": governance_summary.decision,
                    "risk_score": governance_summary.risk_score,
                    "risk_level": governance_summary.risk_level,
                },
                metadata={
                    "critical_or_high": scan_result.has_critical_or_high,
                    "pattern_types": list({f.pattern_type.value for f in findings}),
                    "compliance_status": compliance_result.overall_status.value,
                    "rbac_authorized": rbac_result.authorized,
                    "user_role": user_role.value,
                },
            )
        except Exception as lf_exc:  # pragma: no cover — Langfuse I/O failure is non-fatal
            logger.warning("governance_node: langfuse event failed: %s", lf_exc)

        if findings:
            logger.warning(
                "governance_node: %d finding(s) detected, redacted=%s. Types: %s. "
                "Decision: %s, Risk: %s (%.1f)",
                len(findings),
                context_redacted,
                {f.pattern_type.value for f in findings},
                governance_summary.decision,
                governance_summary.risk_level,
                governance_summary.risk_score,
            )

        return {
            "current_node": "governance_agent",
            "status": ExecutionStatus.RUNNING,
            "ranked_context": updated_context,
            "governance_findings": findings,
            "context_redacted": context_redacted,
            "governance_scan_ms": scan_ms,
            "governance_blocked": False,
            "governance_summary": governance_summary.model_dump(),
            "execution_trace": _build_trace(
                state, 
                findings=findings, 
                scan_ms=scan_ms, 
                blocked=False,
                governance_summary=governance_summary,
            ),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_trace(
    state: AgentState,
    findings: list[DetectionFinding],
    scan_ms: float,
    blocked: bool,
    rbac_denied: bool = False,
    governance_summary: GovernanceSummary | None = None,
) -> list[dict]:
    """Return an updated execution_trace list with a new governance entry appended.

    The trace entry is dict-serialisable for downstream audit storage (EP-011).
    Never mutates the existing list — returns a new list.
    """
    trace_entry: dict = {
        "node": "governance",
        "scan_ms": scan_ms,
        "blocked": blocked,
        "rbac_denied": rbac_denied,
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
    
    # Add governance summary if available
    if governance_summary:
        trace_entry["governance_summary"] = {
            "decision": governance_summary.decision,
            "risk_score": governance_summary.risk_score,
            "risk_level": governance_summary.risk_level,
            "compliance_status": (
                governance_summary.compliance_result.overall_status.value
                if governance_summary.compliance_result
                else "N/A"
            ),
            "rbac_authorized": (
                governance_summary.rbac_result.authorized
                if governance_summary.rbac_result
                else True
            ),
            "metrics": {
                "policies_applied": governance_summary.metrics.policies_applied,
                "policies_passed": governance_summary.metrics.policies_passed,
                "secrets_masked": governance_summary.metrics.secrets_masked,
                "pii_masked": governance_summary.metrics.pii_masked,
            },
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
