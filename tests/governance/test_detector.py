"""Unit tests for SecretPIIDetector — TASK-US031-03.

Covers all acceptance criteria:
  AC-6: scan_context completes in < 200 ms for 128 KB synthetic text
  AC-6: GovernanceScanTimeoutError is raised when the budget is exceeded
  AC-4: findings are aggregated across multiple chunks
  Email allow-list post-filter suppresses matching domains
  Empty context_items returns a result with zero findings
  chunk_id fallback uses list index when neither chunk_id nor id is present
"""
from __future__ import annotations

import time

import pytest

from src.governance.detection.detector import (
    DetectorSettings,
    GovernanceScanTimeoutError,
    SecretPIIDetector,
)
from src.governance.schemas.finding import PatternType, Severity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
GITHUB_PAT = "ghp_" + "A" * 36


def _make_chunk(text: str, chunk_id: str | None = None) -> dict:
    d: dict = {"text": text}
    if chunk_id is not None:
        d["chunk_id"] = chunk_id
    return d


# ---------------------------------------------------------------------------
# Happy-path scan
# ---------------------------------------------------------------------------


def test_scan_detects_aws_key() -> None:
    detector = SecretPIIDetector()
    items = [_make_chunk(f"key={AWS_KEY}", chunk_id="c1")]
    result = detector.scan_context(items)

    assert result.chunks_scanned == 1
    assert any(f.pattern_type == PatternType.AWS_ACCESS_KEY_ID for f in result.findings)
    assert result.has_critical_or_high is True


def test_scan_detects_github_pat() -> None:
    detector = SecretPIIDetector()
    items = [_make_chunk(f"token={GITHUB_PAT}", chunk_id="c2")]
    result = detector.scan_context(items)

    assert any(f.pattern_type == PatternType.GITHUB_PAT for f in result.findings)


def test_scan_aggregates_across_chunks() -> None:
    detector = SecretPIIDetector()
    items = [
        _make_chunk(f"key={AWS_KEY}", chunk_id="c1"),
        _make_chunk("user@example.com", chunk_id="c2"),
    ]
    result = detector.scan_context(items)

    assert result.chunks_scanned == 2
    types = {f.pattern_type for f in result.findings}
    assert PatternType.AWS_ACCESS_KEY_ID in types
    assert PatternType.EMAIL_ADDRESS in types


def test_scan_empty_context_returns_zero_findings() -> None:
    detector = SecretPIIDetector()
    result = detector.scan_context([])

    assert result.chunks_scanned == 0
    assert result.findings == []
    assert result.has_critical_or_high is False


def test_scan_missing_text_field_treated_as_empty() -> None:
    detector = SecretPIIDetector()
    result = detector.scan_context([{"chunk_id": "x"}])

    assert result.findings == []


def test_chunk_id_fallback_uses_index() -> None:
    """When chunk_id and id are absent, list index is used as chunk_id."""
    detector = SecretPIIDetector()
    items = [_make_chunk(f"key={AWS_KEY}")]  # no chunk_id
    result = detector.scan_context(items)

    assert result.findings[0].chunk_id == "0"


def test_chunk_id_uses_id_field_when_chunk_id_absent() -> None:
    detector = SecretPIIDetector()
    items = [{"text": f"key={AWS_KEY}", "id": "my-id"}]
    result = detector.scan_context(items)

    assert result.findings[0].chunk_id == "my-id"


# ---------------------------------------------------------------------------
# Email allow-list
# ---------------------------------------------------------------------------


def test_email_allow_domain_suppresses_finding() -> None:
    settings = DetectorSettings(email_allow_domains=["example.com"])
    detector = SecretPIIDetector(settings=settings)
    items = [_make_chunk("contact user@example.com for info", chunk_id="c1")]
    result = detector.scan_context(items)

    email_findings = [f for f in result.findings if f.pattern_type == PatternType.EMAIL_ADDRESS]
    assert email_findings == []


def test_email_allow_domain_does_not_suppress_other_domains() -> None:
    settings = DetectorSettings(email_allow_domains=["internal.corp"])
    detector = SecretPIIDetector(settings=settings)
    items = [_make_chunk("user@external.org signed in", chunk_id="c1")]
    result = detector.scan_context(items)

    email_findings = [f for f in result.findings if f.pattern_type == PatternType.EMAIL_ADDRESS]
    assert len(email_findings) == 1


# ---------------------------------------------------------------------------
# AC-6: Performance — 128 KB synthetic text completes in < 200 ms
# ---------------------------------------------------------------------------


def test_performance_128kb_under_200ms() -> None:
    """AC-6: scan_context must complete in < 200 ms for ~128 KB text."""
    # 128 KB of inert content with no secrets (worst-case regex backtracking)
    text = ("The quick brown fox jumps over the lazy dog. " * 3000)[:131072]
    detector = SecretPIIDetector()
    items = [_make_chunk(text, chunk_id="perf-chunk")]

    start = time.monotonic()
    result = detector.scan_context(items)
    elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 200, f"Scan took {elapsed_ms:.1f} ms — exceeded 200 ms budget"
    assert result.chunks_scanned == 1


# ---------------------------------------------------------------------------
# AC-6: GovernanceScanTimeoutError is raised (not swallowed)
# ---------------------------------------------------------------------------


def test_timeout_raises_governance_scan_timeout_error() -> None:
    """AC-6: timeout must raise GovernanceScanTimeoutError, not be silently skipped."""
    settings = DetectorSettings(scan_timeout_ms=0.0)
    detector = SecretPIIDetector(settings=settings)

    # Two chunks; after the first chunk the budget (0 ms) is exceeded
    items = [
        _make_chunk("first chunk text", chunk_id="c1"),
        _make_chunk("second chunk text", chunk_id="c2"),
    ]

    with pytest.raises(GovernanceScanTimeoutError, match="exceeded"):
        detector.scan_context(items)


def test_timeout_not_raised_within_budget() -> None:
    """No exception is raised when scan finishes within the configured budget."""
    settings = DetectorSettings(scan_timeout_ms=10_000.0)
    detector = SecretPIIDetector(settings=settings)
    items = [_make_chunk("hello world", chunk_id="c1")]

    # Must not raise
    result = detector.scan_context(items)
    assert result.chunks_scanned == 1


# ---------------------------------------------------------------------------
# scan_duration_ms is recorded in the result
# ---------------------------------------------------------------------------


def test_scan_duration_ms_is_positive() -> None:
    detector = SecretPIIDetector()
    result = detector.scan_context([_make_chunk("hello", chunk_id="c1")])

    assert result.scan_duration_ms >= 0.0


# ---------------------------------------------------------------------------
# Severity metadata preserved on findings
# ---------------------------------------------------------------------------


def test_aws_key_finding_severity_is_critical() -> None:
    detector = SecretPIIDetector()
    result = detector.scan_context([_make_chunk(f"k={AWS_KEY}", chunk_id="c1")])

    aws = [f for f in result.findings if f.pattern_type == PatternType.AWS_ACCESS_KEY_ID]
    assert aws[0].severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# TASK-US031-05: Integration tests — AC-6 (200 ms budget + timeout fail-safe)
# ---------------------------------------------------------------------------


def test_scan_completes_within_200ms_for_32k_token_context() -> None:
    """AC-6: scan_context must complete in < 200 ms for ~32 K tokens (~128 KB)."""
    # ~128 KB ≈ 32 000 tokens at 4 chars/token — inert content, no secrets
    large_text = "normal log line with no secrets\n" * 4_000
    items = [{"chunk_id": "perf-chunk-0", "text": large_text}]

    start = time.monotonic()
    result = SecretPIIDetector().scan_context(items)
    elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 200, f"Scan took {elapsed_ms:.1f} ms — must be < 200 ms"
    assert result.scan_duration_ms < 200


def test_scan_raises_timeout_error_when_budget_exceeded(single_chunk: list[dict]) -> None:
    """AC-6: GovernanceScanTimeoutError is raised when the budget is set to 0 ms."""
    from unittest.mock import patch

    detector = SecretPIIDetector()
    with patch.object(detector._settings, "scan_timeout_ms", 0.0):
        with pytest.raises(GovernanceScanTimeoutError):
            detector.scan_context(single_chunk)
