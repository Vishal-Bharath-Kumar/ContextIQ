"""Unit tests for PatternRegistry — TASK-US031-02.

Covers all acceptance criteria:
  AC-1: scan_text returns findings for AWS key, GitHub PAT, email, credit card, SSN, NI number
  AC-2: valid Luhn card produces a finding; invalid Luhn does not
  AC-3: bare 40-char base-64 string (no keyword context) does NOT match AWS_SECRET_ACCESS_KEY
  AC-4: US_SSN pattern does not match the excluded range 000-00-0000
  AC-5: _truncate_preview returns first 4 chars + ellipsis
  AC-6: all 11 PatternType entries have at least one compiled pattern in _PATTERNS
"""
from __future__ import annotations

import pytest

from src.governance.detection.pattern_registry import (
    PatternRegistry,
    _PATTERNS,
    _truncate_preview,
)
from src.governance.schemas.finding import PatternType, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTRY = PatternRegistry()


def _findings_of_type(
    text: str, pattern_type: PatternType, chunk_id: str = "chunk-1"
) -> list:
    return [
        f
        for f in REGISTRY.scan_text(text, chunk_id)
        if f.pattern_type == pattern_type
    ]


# ---------------------------------------------------------------------------
# AC-6: All 11 PatternTypes covered in _PATTERNS
# ---------------------------------------------------------------------------


def test_all_pattern_types_have_entry() -> None:
    """AC-6: every PatternType has at least one _PatternEntry in _PATTERNS."""
    covered = {entry.pattern_type for entry in _PATTERNS}
    assert covered == set(PatternType)


# ---------------------------------------------------------------------------
# AC-5: _truncate_preview
# ---------------------------------------------------------------------------


def test_truncate_preview_long_string() -> None:
    """AC-5: long match is truncated to first 4 chars + ellipsis."""
    result = _truncate_preview("AKIAXYZ1234567890")
    assert result == "AKIA\u2026"
    assert len(result) == 5


def test_truncate_preview_short_string() -> None:
    """Short strings (<=4 chars) are returned as-is."""
    assert _truncate_preview("AB") == "AB"
    assert _truncate_preview("ABCD") == "ABCD"


def test_truncate_preview_exactly_five() -> None:
    result = _truncate_preview("ABCDE")
    assert result == "ABCD\u2026"


# ---------------------------------------------------------------------------
# AWS Access Key ID
# ---------------------------------------------------------------------------


def test_aws_access_key_detected() -> None:
    text = "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    findings = _findings_of_type(text, PatternType.AWS_ACCESS_KEY_ID)
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].chunk_id == "chunk-1"


def test_aws_access_key_asia_prefix() -> None:
    # ASIA prefix + exactly 16 upper-case/digit chars, terminated by non-word char.
    text = "key=ASIAIOSFODNN7EXAMPLE "
    findings = _findings_of_type(text, PatternType.AWS_ACCESS_KEY_ID)
    assert len(findings) == 1


def test_aws_access_key_no_match_short() -> None:
    text = "AKIA123"  # too short
    findings = _findings_of_type(text, PatternType.AWS_ACCESS_KEY_ID)
    assert findings == []


# ---------------------------------------------------------------------------
# AWS Secret Access Key (context-anchored)
# ---------------------------------------------------------------------------


def test_aws_secret_with_keyword_detected() -> None:
    text = "aws_secret = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    findings = _findings_of_type(text, PatternType.AWS_SECRET_ACCESS_KEY)
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL


def test_aws_secret_bare_base64_not_matched() -> None:
    """AC-3: a bare 40-char base-64 string without keyword context must not match."""
    bare = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    assert len(bare) == 40
    findings = _findings_of_type(bare, PatternType.AWS_SECRET_ACCESS_KEY)
    assert findings == []


def test_secret_access_key_keyword_variant() -> None:
    text = 'SecretAccessKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
    findings = _findings_of_type(text, PatternType.AWS_SECRET_ACCESS_KEY)
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# GitHub PAT
# ---------------------------------------------------------------------------


def test_github_pat_ghp_detected() -> None:
    pat = "ghp_" + "A" * 36
    findings = _findings_of_type(f"token={pat}", PatternType.GITHUB_PAT)
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL


def test_github_pat_gho_detected() -> None:
    pat = "gho_" + "B" * 36
    findings = _findings_of_type(pat, PatternType.GITHUB_PAT)
    assert len(findings) == 1


def test_github_pat_too_short_not_matched() -> None:
    pat = "ghp_" + "A" * 10  # fewer than 36 chars
    findings = _findings_of_type(pat, PatternType.GITHUB_PAT)
    assert findings == []


# ---------------------------------------------------------------------------
# GCP API Key
# ---------------------------------------------------------------------------


def test_gcp_api_key_detected() -> None:
    key = "AIza" + "a" * 35
    findings = _findings_of_type(key, PatternType.GCP_API_KEY)
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# GCP Service Account
# ---------------------------------------------------------------------------


def test_gcp_service_account_detected() -> None:
    text = '{"type": "service_account", "project_id": "my-project"}'
    findings = _findings_of_type(text, PatternType.GCP_SERVICE_ACCOUNT)
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# Azure Connection String
# ---------------------------------------------------------------------------


def test_azure_connection_string_detected() -> None:
    conn = (
        "DefaultEndpointsProtocol=https;AccountName=mystorageaccount;"
        "AccountKey=" + "A" * 44
    )
    findings = _findings_of_type(conn, PatternType.AZURE_CONNECTION_STRING)
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# Email Address
# ---------------------------------------------------------------------------


def test_email_detected() -> None:
    text = "Contact us at user@example.com for support."
    findings = _findings_of_type(text, PatternType.EMAIL_ADDRESS)
    assert len(findings) >= 1
    assert findings[0].severity == Severity.HIGH


def test_multiple_emails_detected() -> None:
    text = "alice@foo.org and bob@bar.co.uk"
    findings = _findings_of_type(text, PatternType.EMAIL_ADDRESS)
    assert len(findings) == 2


# ---------------------------------------------------------------------------
# Credit Card Number (Luhn validation)
# ---------------------------------------------------------------------------


def test_valid_luhn_card_detected() -> None:
    """AC-2: 4111111111111111 is a known valid Luhn test card."""
    text = "Card: 4111111111111111"
    findings = _findings_of_type(text, PatternType.CREDIT_CARD_NUMBER)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_invalid_luhn_card_not_detected() -> None:
    """AC-2: 1234567890123456 fails Luhn and must NOT produce a finding."""
    text = "Card: 1234567890123456"
    findings = _findings_of_type(text, PatternType.CREDIT_CARD_NUMBER)
    assert findings == []


def test_visa_card_with_spaces_detected() -> None:
    """Visa-format card with spaces: 4111 1111 1111 1111."""
    text = "Visa: 4111 1111 1111 1111"
    findings = _findings_of_type(text, PatternType.CREDIT_CARD_NUMBER)
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# Phone Number
# ---------------------------------------------------------------------------


def test_phone_number_e164_detected() -> None:
    text = "+14155552671"
    findings = _findings_of_type(text, PatternType.PHONE_NUMBER)
    assert len(findings) >= 1
    assert findings[0].severity == Severity.MEDIUM


def test_short_number_suppressed() -> None:
    """Sequences with fewer than 7 digits after stripping punctuation are suppressed."""
    text = "call 123"
    findings = _findings_of_type(text, PatternType.PHONE_NUMBER)
    assert findings == []


# ---------------------------------------------------------------------------
# US SSN
# ---------------------------------------------------------------------------


def test_us_ssn_detected() -> None:
    text = "SSN: 123-45-6789"
    findings = _findings_of_type(text, PatternType.US_SSN)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_us_ssn_excluded_range_000() -> None:
    """AC-4: 000-00-0000 must not match (excluded range)."""
    text = "SSN: 000-00-0000"
    findings = _findings_of_type(text, PatternType.US_SSN)
    assert findings == []


def test_us_ssn_excluded_range_666() -> None:
    text = "SSN: 666-12-3456"
    findings = _findings_of_type(text, PatternType.US_SSN)
    assert findings == []


def test_us_ssn_excluded_range_900() -> None:
    text = "SSN: 900-12-3456"
    findings = _findings_of_type(text, PatternType.US_SSN)
    assert findings == []


# ---------------------------------------------------------------------------
# UK NI Number
# ---------------------------------------------------------------------------


def test_uk_ni_detected() -> None:
    text = "NI: AB123456C"
    findings = _findings_of_type(text, PatternType.UK_NI_NUMBER)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_uk_ni_excluded_prefix_bg() -> None:
    """BG prefix is reserved and must not match."""
    text = "BG123456C"
    findings = _findings_of_type(text, PatternType.UK_NI_NUMBER)
    assert findings == []


# ---------------------------------------------------------------------------
# TASK-US031-05: Integration tests using shared conftest fixtures
# ---------------------------------------------------------------------------


def test_all_pattern_types_detected_in_synthetic_text(single_chunk: list[dict]) -> None:
    """AC-2: every PatternType value is detected in SYNTHETIC_TEXT."""
    registry = PatternRegistry()
    chunk = single_chunk[0]
    findings = registry.scan_text(chunk["text"], chunk["chunk_id"])
    found_types = {f.pattern_type for f in findings}

    for pt in PatternType:
        assert pt in found_types, f"PatternType.{pt} not detected in synthetic text"


def test_luhn_invalid_card_not_detected() -> None:
    """AC-2: card number that fails Luhn check must not produce a CREDIT_CARD_NUMBER finding."""
    registry = PatternRegistry()
    findings = registry.scan_text("card: 1234567890123456", "chunk-luhn-1")
    assert not any(f.pattern_type == PatternType.CREDIT_CARD_NUMBER for f in findings)


def test_luhn_valid_card_detected() -> None:
    """AC-2: known-valid Luhn card 4111 1111 1111 1111 must be detected."""
    registry = PatternRegistry()
    findings = registry.scan_text("card: 4111 1111 1111 1111", "chunk-luhn-2")
    assert any(f.pattern_type == PatternType.CREDIT_CARD_NUMBER for f in findings)


def test_invalid_ssn_range_not_detected() -> None:
    """AC-2: 000-xx-xxxx is excluded by the US_SSN pattern."""
    registry = PatternRegistry()
    findings = registry.scan_text("SSN: 000-12-3456", "chunk-ssn-1")
    assert not any(f.pattern_type == PatternType.US_SSN for f in findings)


def test_finding_has_required_fields() -> None:
    """AC-3: every DetectionFinding exposes pattern_type, severity, chunk_id, char_offset, char_end, match_preview."""
    registry = PatternRegistry()
    text = "Contact alice@contoso.com for details."
    chunk_id = "chunk-fields-1"
    findings = registry.scan_text(text, chunk_id)
    email_findings = [f for f in findings if f.pattern_type.value == "EMAIL_ADDRESS"]

    assert len(email_findings) >= 1
    f = email_findings[0]
    assert f.pattern_type.value == "EMAIL_ADDRESS"
    assert f.severity == Severity.HIGH
    assert f.chunk_id == chunk_id
    assert f.char_offset == text.index("alice@contoso.com")
    assert f.char_end == f.char_offset + len("alice@contoso.com")
    assert len(f.match_preview) <= 16


def test_uk_ni_excluded_prefix_gb() -> None:
    text = "GB123456C"
    findings = _findings_of_type(text, PatternType.UK_NI_NUMBER)
    assert findings == []


# ---------------------------------------------------------------------------
# DetectionFinding metadata
# ---------------------------------------------------------------------------


def test_finding_char_offsets() -> None:
    """char_offset and char_end correctly reflect match position."""
    text = "key=AKIAIOSFODNN7EXAMPLE and more"
    findings = _findings_of_type(text, PatternType.AWS_ACCESS_KEY_ID)
    assert len(findings) == 1
    f = findings[0]
    assert text[f.char_offset : f.char_end].startswith("AKIA")


def test_finding_chunk_id_propagated() -> None:
    text = "user@test.org"
    findings = REGISTRY.scan_text(text, "my-chunk-99")
    email_findings = [f for f in findings if f.pattern_type == PatternType.EMAIL_ADDRESS]
    assert all(f.chunk_id == "my-chunk-99" for f in email_findings)


def test_finding_match_preview_truncated() -> None:
    """match_preview must be at most 16 characters (schema constraint)."""
    text = "AKIAIOSFODNN7EXAMPLE"
    findings = _findings_of_type(text, PatternType.AWS_ACCESS_KEY_ID)
    assert findings
    assert len(findings[0].match_preview) <= 16


# ---------------------------------------------------------------------------
# Multi-type synthetic fixture
# ---------------------------------------------------------------------------


def test_scan_synthetic_fixture() -> None:
    """AC-1: scan a block containing all secret/PII types and verify all are found."""
    fixture = "\n".join([
        "AWS key: AKIAIOSFODNN7EXAMPLE",
        "GitHub token: ghp_" + "X" * 36,
        "Email: alice@corp.example.com",
        "Credit card: 4111111111111111",
        "SSN: 123-45-6789",
        "NI: AB123456C",
    ])
    results = REGISTRY.scan_text(fixture, "synth-1")
    found_types = {f.pattern_type for f in results}
    assert PatternType.AWS_ACCESS_KEY_ID in found_types
    assert PatternType.GITHUB_PAT in found_types
    assert PatternType.EMAIL_ADDRESS in found_types
    assert PatternType.CREDIT_CARD_NUMBER in found_types
    assert PatternType.US_SSN in found_types
    assert PatternType.UK_NI_NUMBER in found_types


def test_empty_text_returns_no_findings() -> None:
    assert REGISTRY.scan_text("", "empty-chunk") == []
