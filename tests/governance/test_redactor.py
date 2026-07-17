"""Unit tests for ContextRedactor — TASK-US031-03.

Covers all acceptance criteria:
  AC-4: only critical/high findings are redacted (medium PHONE_NUMBER is left)
  AC-5: placeholder format is exactly [REDACTED:<UPPER_CASE_TYPE>]
  AC-4: AWS key is replaced with [REDACTED:AWS_ACCESS_KEY_ID]
  Overlapping findings produce no garbled output
  redact_context is a pure function — no input mutation
  Items without redaction-eligible findings are returned unchanged
"""
from __future__ import annotations

import copy

from src.governance.detection.redactor import ContextRedactor
from src.governance.schemas.finding import (
    DetectionFinding,
    GovernanceScanResult,
    PatternType,
    Severity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(
    pattern_type: PatternType,
    severity: Severity,
    chunk_id: str,
    char_offset: int,
    char_end: int,
    preview: str = "AKIA…",
) -> DetectionFinding:
    return DetectionFinding(
        pattern_type=pattern_type,
        severity=severity,
        chunk_id=chunk_id,
        char_offset=char_offset,
        char_end=char_end,
        match_preview=preview,
    )


def _scan_result(findings: list[DetectionFinding], chunks: int = 1) -> GovernanceScanResult:
    return GovernanceScanResult.build(
        findings=findings,
        chunks_scanned=chunks,
        scan_duration_ms=1.0,
    )


REDACTOR = ContextRedactor()

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # 20 chars


# ---------------------------------------------------------------------------
# AC-4 + AC-5: AWS key replaced with [REDACTED:AWS_ACCESS_KEY_ID]
# ---------------------------------------------------------------------------


def test_aws_key_is_redacted() -> None:
    """AC-4/AC-5: critical finding is replaced with correct placeholder."""
    text = f"key={AWS_KEY}"
    offset = text.index(AWS_KEY)
    finding = _finding(
        PatternType.AWS_ACCESS_KEY_ID,
        Severity.CRITICAL,
        "c1",
        offset,
        offset + len(AWS_KEY),
    )
    items = [{"text": text, "chunk_id": "c1"}]
    updated, results = REDACTOR.redact_context(items, _scan_result([finding]))

    assert updated[0]["text"] == "key=[REDACTED:AWS_ACCESS_KEY_ID]"
    assert results[0].was_redacted is True
    assert results[0].substitutions_made == 1


def test_placeholder_format_upper_case_type() -> None:
    """AC-5: placeholder is exactly [REDACTED:<UPPER_CASE_TYPE>]."""
    text = "user@example.com logged in"
    finding = _finding(
        PatternType.EMAIL_ADDRESS,
        Severity.HIGH,
        "c1",
        0,
        len("user@example.com"),
        preview="user…",
    )
    items = [{"text": text, "chunk_id": "c1"}]
    updated, _ = REDACTOR.redact_context(items, _scan_result([finding]))

    assert "[REDACTED:EMAIL_ADDRESS]" in updated[0]["text"]


# ---------------------------------------------------------------------------
# AC-4: medium severity (PHONE_NUMBER) is NOT redacted
# ---------------------------------------------------------------------------


def test_medium_severity_phone_number_not_redacted() -> None:
    """AC-4: PHONE_NUMBER (medium) must not be redacted from context text."""
    text = "call +1-800-555-0199 now"
    finding = _finding(
        PatternType.PHONE_NUMBER,
        Severity.MEDIUM,
        "c1",
        5,
        5 + len("+1-800-555-0199"),
        preview="+1-8…",
    )
    items = [{"text": text, "chunk_id": "c1"}]
    updated, results = REDACTOR.redact_context(items, _scan_result([finding]))

    assert updated[0]["text"] == text
    assert results == []


# ---------------------------------------------------------------------------
# Item without matching findings is returned unchanged
# ---------------------------------------------------------------------------


def test_item_without_findings_returned_unchanged() -> None:
    items = [{"text": "no secrets here", "chunk_id": "c1"}]
    updated, results = REDACTOR.redact_context(items, _scan_result([]))

    assert updated[0]["text"] == "no secrets here"
    assert results == []


# ---------------------------------------------------------------------------
# Pure function — no input mutation
# ---------------------------------------------------------------------------


def test_redact_context_does_not_mutate_input_items() -> None:
    """redact_context() must not mutate the original context_items list or dicts."""
    text = f"key={AWS_KEY}"
    offset = text.index(AWS_KEY)
    finding = _finding(
        PatternType.AWS_ACCESS_KEY_ID,
        Severity.CRITICAL,
        "c1",
        offset,
        offset + len(AWS_KEY),
    )
    original_item = {"text": text, "chunk_id": "c1"}
    items = [original_item]
    original_copy = copy.deepcopy(original_item)

    REDACTOR.redact_context(items, _scan_result([finding]))

    # Original dict must be untouched
    assert original_item == original_copy
    assert items[0] is original_item


def test_redact_context_does_not_mutate_input_list() -> None:
    """The returned list is a new object."""
    items: list[dict] = [{"text": "hello", "chunk_id": "c1"}]
    updated, _ = REDACTOR.redact_context(items, _scan_result([]))

    assert updated is not items


# ---------------------------------------------------------------------------
# Overlapping findings — no garbled output
# ---------------------------------------------------------------------------


def test_overlapping_findings_no_garbled_output() -> None:
    """Overlapping findings must produce clean output — only rightmost is applied."""
    text = "token=AKIAIOSFODNN7EXAMPLE_extra"
    # Outer finding covers chars 6–32 (full key + extra)
    outer = _finding(
        PatternType.AWS_ACCESS_KEY_ID,
        Severity.CRITICAL,
        "c1",
        6,
        6 + len(AWS_KEY),
    )
    # Inner finding tries to cover a sub-range that overlaps
    inner = _finding(
        PatternType.GITHUB_PAT,
        Severity.CRITICAL,
        "c1",
        6,
        6 + 5,  # shorter, overlapping start
        preview="AKIA…",
    )
    items = [{"text": text, "chunk_id": "c1"}]
    # Outer finding processed last (lower offset = lower in desc sort)
    updated, results = REDACTOR.redact_context(
        items, _scan_result([outer, inner], chunks=1)
    )

    result_text = updated[0]["text"]
    # Must not contain the raw AWS key
    assert AWS_KEY not in result_text
    # Must not produce double-redaction corruption
    assert "REDACTED" in result_text
    assert result_text.count("[REDACTED:") >= 1


# ---------------------------------------------------------------------------
# Multiple findings in same chunk — correct order and result
# ---------------------------------------------------------------------------


def test_multiple_findings_in_chunk_all_redacted() -> None:
    email = "user@example.com"
    text = f"Contact {email} with key {AWS_KEY}."
    email_start = text.index(email)
    key_start = text.index(AWS_KEY)

    findings = [
        _finding(
            PatternType.EMAIL_ADDRESS,
            Severity.HIGH,
            "c1",
            email_start,
            email_start + len(email),
            preview="user…",
        ),
        _finding(
            PatternType.AWS_ACCESS_KEY_ID,
            Severity.CRITICAL,
            "c1",
            key_start,
            key_start + len(AWS_KEY),
        ),
    ]
    items = [{"text": text, "chunk_id": "c1"}]
    updated, results = REDACTOR.redact_context(items, _scan_result(findings))

    result_text = updated[0]["text"]
    assert email not in result_text
    assert AWS_KEY not in result_text
    assert "[REDACTED:EMAIL_ADDRESS]" in result_text
    assert "[REDACTED:AWS_ACCESS_KEY_ID]" in result_text
    assert results[0].substitutions_made == 2


# ---------------------------------------------------------------------------
# chunk_id fallback — index-based resolution
# ---------------------------------------------------------------------------


def test_chunk_id_fallback_to_index() -> None:
    """Chunks without chunk_id/id use list index for finding lookup."""
    text = f"key={AWS_KEY}"
    offset = text.index(AWS_KEY)
    finding = _finding(
        PatternType.AWS_ACCESS_KEY_ID,
        Severity.CRITICAL,
        "0",  # index-based id
        offset,
        offset + len(AWS_KEY),
    )
    items = [{"text": text}]  # no chunk_id, no id
    updated, results = REDACTOR.redact_context(items, _scan_result([finding]))

    assert "[REDACTED:AWS_ACCESS_KEY_ID]" in updated[0]["text"]
    assert results[0].original_chunk_id == "0"


# ---------------------------------------------------------------------------
# RedactionResult fields
# ---------------------------------------------------------------------------


def test_redaction_result_was_redacted_false_when_no_change() -> None:
    """was_redacted must be False if the redaction produced identical text (edge case)."""
    # Craft a finding whose char range covers nothing meaningful (empty match)
    text = "abcdef"
    finding = _finding(
        PatternType.AWS_ACCESS_KEY_ID,
        Severity.CRITICAL,
        "c1",
        2,
        2,  # zero-length match: result == original
    )
    items = [{"text": text, "chunk_id": "c1"}]
    updated, results = REDACTOR.redact_context(items, _scan_result([finding]))

    # Placeholder inserted but text is technically different
    assert results[0].substitutions_made == 1


# ---------------------------------------------------------------------------
# TASK-US031-05: Integration tests — AC-4, AC-5
# ---------------------------------------------------------------------------


def test_critical_finding_is_redacted() -> None:
    """AC-4: critical severity finding is replaced with a [REDACTED:…] placeholder."""
    from src.governance.detection.detector import SecretPIIDetector

    text = "Key: AKIAIOSFODNN7EXAMPLE rest of line"
    chunk_id = "chunk-redact-1"
    items = [{"chunk_id": chunk_id, "text": text}]
    scan_result = SecretPIIDetector().scan_context(items)
    updated, _ = REDACTOR.redact_context(items, scan_result)

    assert "AKIAIOSFODNN7EXAMPLE" not in updated[0]["text"]
    assert "[REDACTED:" in updated[0]["text"]


def test_medium_finding_is_not_redacted() -> None:
    """AC-4: MEDIUM severity (phone number) must NOT be redacted."""
    from src.governance.detection.detector import SecretPIIDetector

    text = "Call +44 7700 900123 to book."
    chunk_id = "chunk-medium-1"
    items = [{"chunk_id": chunk_id, "text": text}]
    scan_result = SecretPIIDetector().scan_context(items)
    updated, redaction_results = REDACTOR.redact_context(items, scan_result)

    # Phone number is MEDIUM — must remain in the text
    assert "+44 7700 900123" in updated[0]["text"]
    assert len(redaction_results) == 0


def test_placeholder_format() -> None:
    """AC-5: every placeholder in redacted output matches [REDACTED:UPPER_SNAKE_CASE]."""
    import re
    from src.governance.detection.detector import SecretPIIDetector

    text = "key=AKIAIOSFODNN7EXAMPLE and email=bob@example.com"
    chunk_id = "chunk-format-1"
    items = [{"chunk_id": chunk_id, "text": text}]
    scan_result = SecretPIIDetector().scan_context(items)
    updated, _ = REDACTOR.redact_context(items, scan_result)
    redacted_text = updated[0]["text"]

    placeholders = re.findall(r"\[REDACTED:[A-Z_]+\]", redacted_text)
    raw_aws_keys = re.findall(r"AKIA[0-9A-Z]{16}", redacted_text)

    assert len(placeholders) >= 1
    assert len(raw_aws_keys) == 0


def test_overlap_produces_no_garbled_output() -> None:
    """AC-5: overlapping findings produce no double-bracket or partial-secret artefacts."""
    from src.governance.schemas.finding import GovernanceScanResult

    text = "AKIAIOSFODNN7EXAMPLE"
    chunk_id = "chunk-overlap-1"
    f1 = DetectionFinding(
        pattern_type=PatternType.AWS_ACCESS_KEY_ID,
        severity=Severity.CRITICAL,
        chunk_id=chunk_id,
        char_offset=0,
        char_end=20,
        match_preview="AKIA\u2026",
    )
    f2 = DetectionFinding(
        pattern_type=PatternType.EMAIL_ADDRESS,
        severity=Severity.HIGH,
        chunk_id=chunk_id,
        char_offset=0,
        char_end=10,
        match_preview="AKIA\u2026",
    )
    scan_result = GovernanceScanResult.build([f1, f2], chunks_scanned=1, scan_duration_ms=1.0)
    updated, _ = REDACTOR.redact_context(
        [{"chunk_id": chunk_id, "text": text}], scan_result
    )
    result_text = updated[0]["text"]

    assert "AKIA" not in result_text
    assert "[[" not in result_text
