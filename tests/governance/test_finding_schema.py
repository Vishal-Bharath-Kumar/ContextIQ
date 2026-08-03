"""Unit tests for governance detection schemas.

Covers all acceptance criteria for TASK-US031-01:
  AC-1: requires_redaction logic for CRITICAL/HIGH/MEDIUM
  AC-2: GovernanceScanResult.build() has_critical_or_high flag
  AC-3: all 11 PatternType values and 3 Severity values present
  AC-4: DetectionFinding is frozen (immutable)
  AC-5: match_preview max_length enforcement
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.governance.schemas.finding import (
    DetectionFinding,
    GovernanceScanResult,
    PatternType,
    Severity,
)

# ---------------------------------------------------------------------------
# PatternType enum
# ---------------------------------------------------------------------------

EXPECTED_PATTERN_TYPES = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "GCP_API_KEY",
    "GCP_SERVICE_ACCOUNT",
    "AZURE_CONNECTION_STRING",
    "GITHUB_PAT",
    "EMAIL_ADDRESS",
    "CREDIT_CARD_NUMBER",
    "PHONE_NUMBER",
    "US_SSN",
    "UK_NI_NUMBER",
}


def test_pattern_type_has_all_11_values() -> None:
    """AC-3: All 11 PatternType values must be present."""
    actual = {member.value for member in PatternType}
    assert actual == EXPECTED_PATTERN_TYPES


def test_pattern_type_count() -> None:
    assert len(PatternType) == 11


def test_pattern_type_is_str_enum() -> None:
    assert PatternType.AWS_ACCESS_KEY_ID == "AWS_ACCESS_KEY_ID"
    assert isinstance(PatternType.EMAIL_ADDRESS, str)


# ---------------------------------------------------------------------------
# Severity enum
# ---------------------------------------------------------------------------


def test_severity_has_all_3_values() -> None:
    """AC-3: All 3 Severity values must be present."""
    assert set(Severity) == {Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM}


def test_severity_values() -> None:
    assert Severity.CRITICAL == "critical"
    assert Severity.HIGH == "high"
    assert Severity.MEDIUM == "medium"


# ---------------------------------------------------------------------------
# DetectionFinding — frozen model
# ---------------------------------------------------------------------------


def _make_finding(
    pattern_type: PatternType = PatternType.AWS_ACCESS_KEY_ID,
    severity: Severity = Severity.CRITICAL,
    chunk_id: str = "chunk-001",
    char_offset: int = 0,
    char_end: int = 20,
    match_preview: str = "AKIA...",
) -> DetectionFinding:
    return DetectionFinding(
        pattern_type=pattern_type,
        severity=severity,
        chunk_id=chunk_id,
        char_offset=char_offset,
        char_end=char_end,
        match_preview=match_preview,
    )


def test_detection_finding_is_frozen() -> None:
    """AC-4: DetectionFinding must be immutable (ConfigDict frozen=True)."""
    finding = _make_finding()
    with pytest.raises((TypeError, ValidationError)):
        finding.chunk_id = "mutated"  # type: ignore[misc]


def test_requires_redaction_critical() -> None:
    """AC-1: CRITICAL severity requires redaction."""
    finding = _make_finding(severity=Severity.CRITICAL)
    assert finding.requires_redaction is True


def test_requires_redaction_high() -> None:
    """AC-1: HIGH severity requires redaction."""
    finding = _make_finding(
        pattern_type=PatternType.EMAIL_ADDRESS,
        severity=Severity.HIGH,
    )
    assert finding.requires_redaction is True


def test_requires_redaction_medium_false() -> None:
    """AC-1: MEDIUM severity does NOT require redaction."""
    finding = _make_finding(
        pattern_type=PatternType.PHONE_NUMBER,
        severity=Severity.MEDIUM,
    )
    assert finding.requires_redaction is False


def test_match_preview_max_length_enforced() -> None:
    """AC-5: match_preview rejects strings longer than 16 characters."""
    with pytest.raises(ValidationError):
        _make_finding(match_preview="A" * 17)


def test_match_preview_exactly_16_chars_allowed() -> None:
    finding = _make_finding(match_preview="A" * 16)
    assert len(finding.match_preview) == 16


def test_char_offset_non_negative() -> None:
    with pytest.raises(ValidationError):
        _make_finding(char_offset=-1)


def test_char_end_non_negative() -> None:
    with pytest.raises(ValidationError):
        _make_finding(char_end=-1)


# ---------------------------------------------------------------------------
# GovernanceScanResult.build()
# ---------------------------------------------------------------------------


def test_build_sets_has_critical_or_high_true_for_critical() -> None:
    """AC-2: has_critical_or_high is True when a CRITICAL finding is present."""
    findings = [_make_finding(severity=Severity.CRITICAL)]
    result = GovernanceScanResult.build(
        findings=findings,
        chunks_scanned=1,
        scan_duration_ms=10.0,
    )
    assert result.has_critical_or_high is True


def test_build_sets_has_critical_or_high_true_for_high() -> None:
    """AC-2: has_critical_or_high is True when a HIGH finding is present."""
    findings = [
        _make_finding(
            pattern_type=PatternType.EMAIL_ADDRESS,
            severity=Severity.HIGH,
        )
    ]
    result = GovernanceScanResult.build(
        findings=findings,
        chunks_scanned=2,
        scan_duration_ms=5.0,
    )
    assert result.has_critical_or_high is True


def test_build_sets_has_critical_or_high_false_for_medium_only() -> None:
    """AC-2: has_critical_or_high is False when all findings are MEDIUM."""
    findings = [
        _make_finding(
            pattern_type=PatternType.PHONE_NUMBER,
            severity=Severity.MEDIUM,
        )
    ]
    result = GovernanceScanResult.build(
        findings=findings,
        chunks_scanned=3,
        scan_duration_ms=8.0,
    )
    assert result.has_critical_or_high is False


def test_build_sets_has_critical_or_high_false_for_empty_findings() -> None:
    """has_critical_or_high is False when there are no findings."""
    result = GovernanceScanResult.build(
        findings=[],
        chunks_scanned=5,
        scan_duration_ms=12.5,
    )
    assert result.has_critical_or_high is False
    assert result.findings == []


def test_build_mixed_severities_sets_true() -> None:
    """has_critical_or_high is True when mixed (MEDIUM + HIGH) findings."""
    findings = [
        _make_finding(pattern_type=PatternType.PHONE_NUMBER, severity=Severity.MEDIUM),
        _make_finding(pattern_type=PatternType.US_SSN, severity=Severity.HIGH),
    ]
    result = GovernanceScanResult.build(
        findings=findings,
        chunks_scanned=2,
        scan_duration_ms=3.0,
    )
    assert result.has_critical_or_high is True


def test_scan_result_is_frozen() -> None:
    """GovernanceScanResult is also immutable."""
    result = GovernanceScanResult.build(
        findings=[],
        chunks_scanned=1,
        scan_duration_ms=1.0,
    )
    with pytest.raises((TypeError, ValidationError)):
        result.chunks_scanned = 99  # type: ignore[misc]


def test_scan_result_chunks_scanned_non_negative() -> None:
    with pytest.raises(ValidationError):
        GovernanceScanResult(
            findings=[],
            chunks_scanned=-1,
            scan_duration_ms=1.0,
            has_critical_or_high=False,
        )


def test_scan_result_duration_non_negative() -> None:
    with pytest.raises(ValidationError):
        GovernanceScanResult(
            findings=[],
            chunks_scanned=0,
            scan_duration_ms=-0.1,
            has_critical_or_high=False,
        )


def test_build_preserves_findings_list() -> None:
    findings = [
        _make_finding(chunk_id="c1"),
        _make_finding(
            chunk_id="c2",
            severity=Severity.MEDIUM,
            pattern_type=PatternType.PHONE_NUMBER,
        ),
    ]
    result = GovernanceScanResult.build(
        findings=findings,
        chunks_scanned=10,
        scan_duration_ms=50.0,
    )
    assert len(result.findings) == 2
    assert result.chunks_scanned == 10
    assert result.scan_duration_ms == 50.0
