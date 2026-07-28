"""Compliance validation for governance checks.

Validates content against compliance standards:
- GDPR (EU General Data Protection Regulation)
- SOC2 (System and Organization Controls 2)
- HIPAA (Health Insurance Portability and Accountability Act)
- PCI-DSS (Payment Card Industry Data Security Standard)
"""
from __future__ import annotations

import logging
from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel, Field

from src.governance.schemas.finding import DetectionFinding, PatternType, Severity

logger = logging.getLogger(__name__)


class ComplianceStandard(StrEnum):
    """Supported compliance standards."""

    GDPR = "GDPR"
    SOC2 = "SOC2"
    HIPAA = "HIPAA"
    PCI_DSS = "PCI_DSS"
    CCPA = "CCPA"


class ComplianceStatus(StrEnum):
    """Compliance check result status."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_APPLICABLE = "N/A"


class ComplianceCheck(BaseModel):
    """Result of a compliance validation check."""

    standard: ComplianceStandard
    status: ComplianceStatus
    message: str = ""
    findings_count: int = Field(ge=0, default=0)
    violations: list[str] = Field(default_factory=list)


class ComplianceResult(BaseModel):
    """Aggregate compliance validation result."""

    checks: list[ComplianceCheck]
    overall_status: ComplianceStatus
    risk_score: float = Field(ge=0.0, le=10.0)  # 0-10 scale

    @property
    def is_compliant(self) -> bool:
        """True if all applicable checks passed."""
        return all(
            check.status in (ComplianceStatus.PASS, ComplianceStatus.NOT_APPLICABLE)
            for check in self.checks
        )


class _ComplianceRule(NamedTuple):
    """Internal rule mapping pattern types to compliance violations."""

    standard: ComplianceStandard
    severity_threshold: Severity
    pattern_types: list[PatternType]
    message: str


# Compliance rules mapping
_COMPLIANCE_RULES: list[_ComplianceRule] = [
    _ComplianceRule(
        standard=ComplianceStandard.GDPR,
        severity_threshold=Severity.HIGH,
        pattern_types=[
            PatternType.EMAIL_ADDRESS,
            PatternType.PHONE_NUMBER,
            PatternType.US_SSN,
            PatternType.UK_NI_NUMBER,
            PatternType.IP_ADDRESS,
        ],
        message="Personal data detected without proper consent/anonymization controls",
    ),
    _ComplianceRule(
        standard=ComplianceStandard.SOC2,
        severity_threshold=Severity.CRITICAL,
        pattern_types=[
            PatternType.AWS_ACCESS_KEY_ID,
            PatternType.AWS_SECRET_ACCESS_KEY,
            PatternType.GCP_API_KEY,
            PatternType.AZURE_CONNECTION_STRING,
            PatternType.GITHUB_PAT,
            PatternType.DATABASE_URL,
            PatternType.PRIVATE_KEY,
        ],
        message="Credentials exposed in logs/context violates access control requirements",
    ),
    _ComplianceRule(
        standard=ComplianceStandard.HIPAA,
        severity_threshold=Severity.HIGH,
        pattern_types=[
            PatternType.US_SSN,
            PatternType.PHONE_NUMBER,
            PatternType.EMAIL_ADDRESS,
        ],
        message="Protected Health Information (PHI) detected without encryption",
    ),
    _ComplianceRule(
        standard=ComplianceStandard.PCI_DSS,
        severity_threshold=Severity.HIGH,
        pattern_types=[
            PatternType.CREDIT_CARD_NUMBER,
        ],
        message="Primary Account Number (PAN) detected in cleartext",
    ),
    _ComplianceRule(
        standard=ComplianceStandard.CCPA,
        severity_threshold=Severity.HIGH,
        pattern_types=[
            PatternType.EMAIL_ADDRESS,
            PatternType.PHONE_NUMBER,
            PatternType.IP_ADDRESS,
            PatternType.US_SSN,
        ],
        message="California Consumer Privacy Act: personal information detected",
    ),
]


class ComplianceValidator:
    """Validates findings against compliance standards."""

    def __init__(self) -> None:
        """Initialize the compliance validator."""
        pass

    def validate(
        self,
        findings: list[DetectionFinding],
        enabled_standards: list[ComplianceStandard] | None = None,
    ) -> ComplianceResult:
        """Validate findings against enabled compliance standards.

        Args:
            findings: List of detection findings from governance scan
            enabled_standards: List of standards to check, defaults to all

        Returns:
            ComplianceResult with check results and risk score
        """
        if enabled_standards is None:
            enabled_standards = list(ComplianceStandard)

        checks: list[ComplianceCheck] = []
        violations_count = 0

        for rule in _COMPLIANCE_RULES:
            if rule.standard not in enabled_standards:
                continue

            # Find findings that violate this rule
            violations = [
                f
                for f in findings
                if f.pattern_type in rule.pattern_types
                and self._severity_meets_threshold(f.severity, rule.severity_threshold)
            ]

            if violations:
                status = ComplianceStatus.FAIL
                violations_count += len(violations)
                violation_details = [
                    f"{v.pattern_type.value} at chunk {v.chunk_id}"
                    for v in violations[:5]  # Limit to first 5
                ]
                if len(violations) > 5:
                    violation_details.append(f"... and {len(violations) - 5} more")
            else:
                status = ComplianceStatus.PASS
                violation_details = []

            checks.append(
                ComplianceCheck(
                    standard=rule.standard,
                    status=status,
                    message=rule.message if violations else "No violations detected",
                    findings_count=len(violations),
                    violations=violation_details,
                )
            )

        # Calculate overall status and risk score
        overall_status = self._calculate_overall_status(checks)
        risk_score = self._calculate_risk_score(findings, violations_count)

        return ComplianceResult(
            checks=checks,
            overall_status=overall_status,
            risk_score=risk_score,
        )

    def _severity_meets_threshold(
        self, severity: Severity, threshold: Severity
    ) -> bool:
        """Check if severity meets or exceeds threshold."""
        severity_order = {
            Severity.INFO: 0,
            Severity.LOW: 1,
            Severity.MEDIUM: 2,
            Severity.HIGH: 3,
            Severity.CRITICAL: 4,
        }
        return severity_order.get(severity, 0) >= severity_order.get(threshold, 0)

    def _calculate_overall_status(
        self, checks: list[ComplianceCheck]
    ) -> ComplianceStatus:
        """Calculate overall compliance status from individual checks."""
        if any(check.status == ComplianceStatus.FAIL for check in checks):
            return ComplianceStatus.FAIL
        if any(check.status == ComplianceStatus.WARNING for check in checks):
            return ComplianceStatus.WARNING
        return ComplianceStatus.PASS

    def _calculate_risk_score(
        self, findings: list[DetectionFinding], violations_count: int
    ) -> float:
        """Calculate risk score (0-10) based on findings and violations.

        Scoring:
        - 0.0-2.0: Low risk
        - 2.1-5.0: Medium risk
        - 5.1-8.0: High risk
        - 8.1-10.0: Critical risk
        """
        if not findings:
            return 0.0

        # Weight by severity
        severity_weights = {
            Severity.INFO: 0.1,
            Severity.LOW: 0.5,
            Severity.MEDIUM: 1.5,
            Severity.HIGH: 3.0,
            Severity.CRITICAL: 5.0,
        }

        total_weight = sum(
            severity_weights.get(f.severity, 0) for f in findings
        )

        # Add violation penalty
        violation_penalty = min(violations_count * 0.5, 3.0)

        # Calculate final score (capped at 10.0)
        risk_score = min(total_weight + violation_penalty, 10.0)

        return round(risk_score, 1)
