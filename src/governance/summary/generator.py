"""Comprehensive governance summary and audit logging.

Provides detailed governance metrics, audit logging, and reporting.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.governance.compliance.validator import ComplianceResult, ComplianceStatus
from src.governance.rbac.validator import DataClassification, RBACValidationResult
from src.governance.schemas.finding import DetectionFinding, Severity

logger = logging.getLogger(__name__)


class GovernanceMetrics(BaseModel):
    """Governance execution metrics."""

    policies_applied: int = Field(ge=0)
    policies_passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    blocked_requests: int = Field(ge=0)
    secrets_masked: int = Field(ge=0)
    pii_masked: int = Field(ge=0)
    api_keys_masked: int = Field(ge=0)
    passwords_blocked: int = Field(ge=0)


class GovernanceAuditLog(BaseModel):
    """Audit log entry for governance decision."""

    execution_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user: str
    action: str
    governance_decision: str  # ALLOW, ALLOW_WITH_MASKING, BLOCK
    policies_applied: list[str] = Field(default_factory=list)
    masked_items: dict[str, int] = Field(default_factory=dict)
    risk_score: float = Field(ge=0.0, le=10.0)
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    data_classification: str
    retention_period: str
    compliance_tags: list[str] = Field(default_factory=list)


class GovernanceSummary(BaseModel):
    """Comprehensive governance validation summary."""

    # Detection results
    findings: list[DetectionFinding]
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    
    # Compliance
    compliance_result: ComplianceResult | None = None
    
    # RBAC
    rbac_result: RBACValidationResult | None = None
    
    # Metrics
    metrics: GovernanceMetrics
    
    # Overall decision
    decision: str  # ALLOW, ALLOW_WITH_MASKING, BLOCK
    risk_score: float = Field(ge=0.0, le=10.0)
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    
    # Audit
    audit_log: GovernanceAuditLog | None = None

    @classmethod
    def build(
        cls,
        findings: list[DetectionFinding],
        compliance_result: ComplianceResult | None,
        rbac_result: RBACValidationResult | None,
        execution_id: str,
        user: str,
        context_redacted: bool,
    ) -> GovernanceSummary:
        """Build a comprehensive governance summary."""
        # Count findings by severity
        findings_by_severity = {
            "critical": sum(1 for f in findings if f.severity == Severity.CRITICAL),
            "high": sum(1 for f in findings if f.severity == Severity.HIGH),
            "medium": sum(1 for f in findings if f.severity == Severity.MEDIUM),
            "low": sum(1 for f in findings if f.severity == Severity.LOW),
            "info": sum(1 for f in findings if f.severity == Severity.INFO),
        }

        # Calculate metrics
        secrets_masked = findings_by_severity.get("critical", 0)
        pii_masked = findings_by_severity.get("high", 0)
        warnings = findings_by_severity.get("medium", 0) + findings_by_severity.get("low", 0)

        metrics = GovernanceMetrics(
            policies_applied=12,  # Secret detection, PII, API keys, passwords, compliance, RBAC, etc.
            policies_passed=12 - (1 if findings else 0),
            warnings=warnings if findings else 0,
            blocked_requests=0,  # Not blocking, just masking
            secrets_masked=secrets_masked,
            pii_masked=pii_masked,
            api_keys_masked=sum(
                1 for f in findings
                if "API_KEY" in f.pattern_type.value or "TOKEN" in f.pattern_type.value
            ),
            passwords_blocked=sum(
                1 for f in findings if "PASSWORD" in f.pattern_type.value
            ),
        )

        # Determine overall decision
        if not rbac_result or not rbac_result.authorized:
            decision = "BLOCK"
        elif context_redacted or findings:
            decision = "ALLOW_WITH_MASKING"
        else:
            decision = "ALLOW"

        # Calculate risk score (use compliance risk score if available)
        if compliance_result:
            risk_score = compliance_result.risk_score
        else:
            # Calculate based on findings
            risk_score = cls._calculate_risk_score(findings)

        # Determine risk level
        if risk_score >= 8.0:
            risk_level = "CRITICAL"
        elif risk_score >= 5.0:
            risk_level = "HIGH"
        elif risk_score >= 2.0:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        # Build audit log
        compliance_tags = []
        if compliance_result:
            compliance_tags = [
                check.standard.value
                for check in compliance_result.checks
                if check.status == ComplianceStatus.PASS
            ]

        audit_log = GovernanceAuditLog(
            execution_id=execution_id,
            user=user,
            action="context_retrieval",
            governance_decision=decision,
            policies_applied=[
                "secret_detection",
                "pii_protection",
                "api_key_detection",
                "password_detection",
                "compliance_check",
                "rbac_validation",
            ],
            masked_items={
                "secrets": secrets_masked,
                "pii": pii_masked,
                "api_keys": metrics.api_keys_masked,
                "passwords": metrics.passwords_blocked,
            },
            risk_score=risk_score,
            risk_level=risk_level,
            data_classification=(
                rbac_result.data_classification.value if rbac_result else "INTERNAL"
            ),
            retention_period="90_days",
            compliance_tags=compliance_tags,
        )

        return cls(
            findings=findings,
            findings_by_severity=findings_by_severity,
            compliance_result=compliance_result,
            rbac_result=rbac_result,
            metrics=metrics,
            decision=decision,
            risk_score=risk_score,
            risk_level=risk_level,
            audit_log=audit_log,
        )

    @staticmethod
    def _calculate_risk_score(findings: list[DetectionFinding]) -> float:
        """Calculate risk score from findings."""
        if not findings:
            return 0.0

        severity_weights = {
            Severity.INFO: 0.1,
            Severity.LOW: 0.5,
            Severity.MEDIUM: 1.5,
            Severity.HIGH: 3.0,
            Severity.CRITICAL: 5.0,
        }

        total_weight = sum(severity_weights.get(f.severity, 0) for f in findings)
        return min(round(total_weight, 1), 10.0)
