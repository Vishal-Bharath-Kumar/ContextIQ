"""Governance detection schemas.

Defines the data contracts shared by SecretPIIDetector, ContextRedactor,
and governance_node(), and extended by the US-032 OPA enforcement layer.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PatternType(StrEnum):
    """All detectable secret and PII categories."""

    # Cloud provider secrets
    AWS_ACCESS_KEY_ID = "AWS_ACCESS_KEY_ID"
    AWS_SECRET_ACCESS_KEY = "AWS_SECRET_ACCESS_KEY"  # noqa: S105
    GCP_API_KEY = "GCP_API_KEY"
    GCP_SERVICE_ACCOUNT = "GCP_SERVICE_ACCOUNT"
    AZURE_CONNECTION_STRING = "AZURE_CONNECTION_STRING"
    # SCM tokens
    GITHUB_PAT = "GITHUB_PAT"
    # PII
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    CREDIT_CARD_NUMBER = "CREDIT_CARD_NUMBER"
    PHONE_NUMBER = "PHONE_NUMBER"
    US_SSN = "US_SSN"
    UK_NI_NUMBER = "UK_NI_NUMBER"


class Severity(StrEnum):
    """Severity levels for governance findings."""

    CRITICAL = "critical"  # credentials that enable direct cloud/SCM access
    HIGH = "high"  # PII that constitutes personal data under GDPR/CCPA
    MEDIUM = "medium"  # lower-risk PII (phone numbers, generic emails)


class DetectionFinding(BaseModel):
    """Immutable record of a single regex match within a context chunk."""

    model_config = ConfigDict(frozen=True)

    pattern_type: PatternType
    severity: Severity
    # UUID of the context chunk where the match was found (AC-3).
    chunk_id: str = Field(
        description="Context chunk identifier; may be a UUID string or a connector-native ID.",
    )
    # Character offset of the match start within the chunk text (AC-3).
    char_offset: int = Field(ge=0)
    # Character offset of the match end (exclusive).
    char_end: int = Field(ge=0)
    # Truncated preview of the matched text, max 16 chars.
    # Never stores the full secret — only enough for debugging.
    match_preview: str = Field(
        description=(
            "First 4 chars + '...' of match. Used for audit log; never logs the full value."
        ),
        max_length=16,
    )

    @property
    def requires_redaction(self) -> bool:
        """True for critical and high severity findings (AC-4)."""
        return self.severity in (Severity.CRITICAL, Severity.HIGH)


class GovernanceScanResult(BaseModel):
    """Output of a full context scan across all chunks."""

    model_config = ConfigDict(frozen=True)

    findings: list[DetectionFinding]
    # Number of chunks scanned; useful for audit rate calculation.
    chunks_scanned: int = Field(ge=0)
    # Wall-clock scan duration in milliseconds; validated against 200 ms SLA.
    scan_duration_ms: float = Field(ge=0.0)
    # True if any critical or high severity findings were found (convenience flag).
    has_critical_or_high: bool

    @classmethod
    def build(
        cls,
        findings: list[DetectionFinding],
        chunks_scanned: int,
        scan_duration_ms: float,
    ) -> GovernanceScanResult:
        """Construct a result, computing has_critical_or_high from findings."""
        critical_or_high = any(f.requires_redaction for f in findings)
        return cls(
            findings=findings,
            chunks_scanned=chunks_scanned,
            scan_duration_ms=scan_duration_ms,
            has_critical_or_high=critical_or_high,
        )
