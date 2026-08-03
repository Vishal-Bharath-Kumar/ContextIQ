# TASK-US031-05 — Integration Tests Covering All 7 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US031-05 |
| User Story | US-031 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the integration and unit test suite covering all 7 US-031 acceptance criteria: mandatory node position, AC-2 pattern detection across all 11 types, finding schema (pattern_type/severity/chunk_id/offset), critical/high auto-redaction, `[REDACTED:<type>]` placeholder format, 200 ms scan budget, and execution trace recording.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-benchmark, `unittest.mock`

**File locations:**
- `tests/governance/test_pattern_registry.py` — AC-2, AC-3 (pattern coverage + finding shape)
- `tests/governance/test_detector.py` — AC-6 (200 ms budget, timeout behaviour)
- `tests/governance/test_redactor.py` — AC-4, AC-5 (redaction logic + placeholder format)
- `tests/governance/test_governance_node.py` — AC-1, AC-7 (node position + audit trace)

---

### Synthetic test fixtures

```python
# tests/governance/conftest.py
import pytest
from uuid import uuid4

CHUNK_ID = str(uuid4())

# A text block embedding one of each detectable pattern type
SYNTHETIC_TEXT = f"""
Meeting notes — {CHUNK_ID}

Team contact: alice@contoso.com
AWS Key: AKIAIOSFODNN7EXAMPLE
AWS Secret: aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
GCP Key: AIzaSyB4example35charslongXXXXXXXXXX
GitHub PAT: ghp_1234567890abcdefghijklmnopqrstuvwxyz12
Credit Card: 4111 1111 1111 1111
SSN: 123-45-6789
NI: AB123456C
Phone: +44 7700 900123
Azure: DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=dGVzdGtleXZhbHVlMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODk=
Service account: "type": "service_account"
"""

@pytest.fixture
def single_chunk():
    return [{"chunk_id": CHUNK_ID, "text": SYNTHETIC_TEXT}]

@pytest.fixture
def clean_chunk():
    return [{"chunk_id": CHUNK_ID, "text": "No secrets here. Just a normal meeting summary."}]

@pytest.fixture
def medium_only_chunk():
    return [{"chunk_id": CHUNK_ID, "text": "Call us at +44 7700 900123 for support."}]
```

---

### AC-2 — All pattern types detected

```python
# tests/governance/test_pattern_registry.py
from src.governance.detection.pattern_registry import PatternRegistry
from src.governance.schemas.finding            import PatternType

def test_all_pattern_types_detected_in_synthetic_text(single_chunk):
    registry = PatternRegistry()
    findings = registry.scan_text(single_chunk[0]["text"], CHUNK_ID)
    found_types = {f.pattern_type for f in findings}

    for pt in PatternType:
        assert pt in found_types, f"PatternType.{pt} not detected in synthetic text"


def test_luhn_invalid_card_not_detected():
    registry = PatternRegistry()
    findings = registry.scan_text("card: 1234567890123456", CHUNK_ID)
    assert not any(f.pattern_type == PatternType.CREDIT_CARD_NUMBER for f in findings)


def test_luhn_valid_card_detected():
    registry = PatternRegistry()
    findings = registry.scan_text("card: 4111 1111 1111 1111", CHUNK_ID)
    assert any(f.pattern_type == PatternType.CREDIT_CARD_NUMBER for f in findings)


def test_invalid_ssn_range_not_detected():
    registry = PatternRegistry()
    # 000-xx-xxxx is excluded by pattern
    findings = registry.scan_text("SSN: 000-12-3456", CHUNK_ID)
    assert not any(f.pattern_type == PatternType.US_SSN for f in findings)
```

---

### AC-3 — Finding shape: pattern_type, severity, chunk_id, char_offset

```python
def test_finding_has_required_fields():
    from src.governance.detection.pattern_registry import PatternRegistry
    from src.governance.schemas.finding            import Severity

    registry = PatternRegistry()
    text     = "Contact alice@contoso.com for details."
    findings = registry.scan_text(text, CHUNK_ID)
    email_findings = [f for f in findings if f.pattern_type.value == "EMAIL_ADDRESS"]

    assert len(email_findings) >= 1
    f = email_findings[0]
    assert f.pattern_type.value == "EMAIL_ADDRESS"
    assert f.severity           == Severity.HIGH
    assert f.chunk_id           == CHUNK_ID
    assert f.char_offset        == text.index("alice@contoso.com")
    assert f.char_end           == f.char_offset + len("alice@contoso.com")
    assert len(f.match_preview) <= 16
```

---

### AC-4 — Critical/high findings trigger automatic redaction

```python
# tests/governance/test_redactor.py
def test_critical_finding_is_redacted():
    from src.governance.detection.detector  import SecretPIIDetector
    from src.governance.detection.redactor  import ContextRedactor

    text    = "Key: AKIAIOSFODNN7EXAMPLE rest of line"
    items   = [{"chunk_id": CHUNK_ID, "text": text}]
    result  = SecretPIIDetector().scan_context(items)
    updated, _ = ContextRedactor().redact_context(items, result)

    assert "AKIAIOSFODNN7EXAMPLE" not in updated[0]["text"]
    assert "[REDACTED:" in updated[0]["text"]


def test_medium_finding_is_not_redacted():
    from src.governance.detection.detector import SecretPIIDetector
    from src.governance.detection.redactor import ContextRedactor

    text   = "Call +44 7700 900123 to book."
    items  = [{"chunk_id": CHUNK_ID, "text": text}]
    result = SecretPIIDetector().scan_context(items)
    updated, redaction_results = ContextRedactor().redact_context(items, result)

    # Phone number is MEDIUM — must NOT be redacted
    assert "+44 7700 900123" in updated[0]["text"]
    assert len(redaction_results) == 0
```

---

### AC-5 — Placeholder format is exactly `[REDACTED:<TYPE>]`

```python
def test_placeholder_format():
    from src.governance.detection.detector import SecretPIIDetector
    from src.governance.detection.redactor import ContextRedactor
    import re

    text   = "key=AKIAIOSFODNN7EXAMPLE and email=bob@example.com"
    items  = [{"chunk_id": CHUNK_ID, "text": text}]
    result = SecretPIIDetector().scan_context(items)
    updated, _ = ContextRedactor().redact_context(items, result)
    redacted_text = updated[0]["text"]

    # Every placeholder must match [REDACTED:UPPER_SNAKE_CASE]
    placeholders = re.findall(r"\[REDACTED:[A-Z_]+\]", redacted_text)
    raw_secrets  = re.findall(r"AKIA[0-9A-Z]{16}", redacted_text)

    assert len(placeholders) >= 1
    assert len(raw_secrets)  == 0


def test_overlap_produces_no_garbled_output():
    from src.governance.detection.redactor import ContextRedactor
    from src.governance.schemas.finding    import DetectionFinding, PatternType, Severity, GovernanceScanResult

    text = "AKIAIOSFODNN7EXAMPLE"
    # Simulate two overlapping findings for the same span
    f1 = DetectionFinding(
        pattern_type=PatternType.AWS_ACCESS_KEY_ID, severity=Severity.CRITICAL,
        chunk_id=CHUNK_ID, char_offset=0, char_end=20, match_preview="AKIA…",
    )
    f2 = DetectionFinding(
        pattern_type=PatternType.EMAIL_ADDRESS, severity=Severity.HIGH,
        chunk_id=CHUNK_ID, char_offset=0, char_end=10, match_preview="AKIA…",
    )
    scan_result = GovernanceScanResult.build([f1, f2], 1, 1.0)
    updated, _ = ContextRedactor().redact_context(
        [{"chunk_id": CHUNK_ID, "text": text}], scan_result
    )
    # Must not contain partial raw text or double brackets
    assert "AKIA" not in updated[0]["text"]
    assert "[[" not in updated[0]["text"]
```

---

### AC-6 — 200 ms scan budget

```python
# tests/governance/test_detector.py
def test_scan_completes_within_200ms_for_32k_token_context():
    import time
    from src.governance.detection.detector import SecretPIIDetector

    # ~128 KB ≈ 32 000 tokens at 4 chars/token
    large_text = "normal log line with no secrets\n" * 4_000
    items  = [{"chunk_id": str(i), "text": large_text} for i in range(1)]
    start  = time.monotonic()
    result = SecretPIIDetector().scan_context(items)
    elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 200, f"Scan took {elapsed_ms:.1f} ms — must be < 200 ms"
    assert result.scan_duration_ms < 200


def test_scan_raises_timeout_error_when_budget_exceeded(single_chunk):
    import pytest
    from unittest.mock import patch
    from src.governance.detection.detector import SecretPIIDetector, GovernanceScanTimeoutError

    # Force immediate timeout by setting budget to 0 ms
    detector = SecretPIIDetector()
    with patch.object(detector._settings, "scan_timeout_ms", 0.0):
        with pytest.raises(GovernanceScanTimeoutError):
            detector.scan_context(single_chunk)
```

---

### AC-1 + AC-7 — Mandatory node position and execution trace

```python
# tests/governance/test_governance_node.py
from unittest.mock import patch, MagicMock

def test_governance_node_appends_to_execution_trace(single_chunk):
    from src.governance.nodes.governance_node import governance_node

    state  = {"ranked_context": single_chunk, "execution_plan": {}}
    result = governance_node(state)

    assert "execution_trace" in result
    trace = result["execution_trace"]
    assert len(trace) >= 1
    gov_entry = next((e for e in trace if e.get("node") == "governance"), None)
    assert gov_entry is not None
    assert "findings" in gov_entry
    assert "scan_ms"  in gov_entry


def test_governance_node_blocks_on_scan_timeout(single_chunk):
    from src.governance.nodes.governance_node  import governance_node
    from src.governance.detection.detector      import GovernanceScanTimeoutError

    with patch(
        "src.governance.nodes.governance_node._DETECTOR.scan_context",
        side_effect=GovernanceScanTimeoutError("timeout"),
    ):
        state  = {"ranked_context": single_chunk, "execution_plan": {}}
        result = governance_node(state)

    assert result["governance_blocked"]  is True
    assert result["ranked_context"]      == []


def test_governance_node_redacts_critical_findings(single_chunk):
    from src.governance.nodes.governance_node import governance_node

    state  = {"ranked_context": single_chunk, "execution_plan": {}}
    result = governance_node(state)

    assert result["context_redacted"] is True
    for item in result["ranked_context"]:
        # Raw AWS key must not appear in any chunk after governance
        assert "AKIAIOSFODNN7EXAMPLE" not in item.get("text", "")


def test_governance_node_does_not_redact_medium_findings(medium_only_chunk):
    from src.governance.nodes.governance_node import governance_node

    state  = {"ranked_context": medium_only_chunk, "execution_plan": {}}
    result = governance_node(state)

    assert result["context_redacted"] is False
    # Original text preserved
    assert "+44 7700 900123" in result["ranked_context"][0]["text"]


def test_governance_node_clean_context(clean_chunk):
    from src.governance.nodes.governance_node import governance_node

    state  = {"ranked_context": clean_chunk, "execution_plan": {}}
    result = governance_node(state)

    assert result["governance_findings"]  == []
    assert result["context_redacted"]     is False
    assert result["governance_blocked"]   is False
    assert result["ranked_context"]       == clean_chunk
```

## Acceptance Criteria

- [ ] All 7 AC-level tests pass in CI
- [ ] `test_all_pattern_types_detected_in_synthetic_text` confirms all 11 `PatternType` values are covered
- [ ] `test_overlap_produces_no_garbled_output` confirms no double-bracket or partial-secret artefacts
- [ ] `test_scan_completes_within_200ms_for_32k_token_context` passes on CI hardware
- [ ] `test_governance_node_blocks_on_scan_timeout` confirms `ranked_context=[]` on timeout (fail-safe)
- [ ] `test_governance_node_clean_context` confirms zero-finding path returns original context unchanged

## Dependencies

- TASK-US031-01 (`PatternType`, `Severity`, `DetectionFinding`, `GovernanceScanResult`)
- TASK-US031-02 (`PatternRegistry`)
- TASK-US031-03 (`SecretPIIDetector`, `GovernanceScanTimeoutError`, `ContextRedactor`)
- TASK-US031-04 (`governance_node`, `AgentState` extensions)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Performance test is in the default `pytest` run (not gated behind `--benchmark-only`) since it has a hard pass/fail threshold (< 200 ms)
- [ ] `mypy --strict` passes; no `ruff` lint errors
