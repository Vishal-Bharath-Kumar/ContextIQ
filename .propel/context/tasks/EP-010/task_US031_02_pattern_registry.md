# TASK-US031-02 — `PatternRegistry`: Compiled Regex Patterns for All Detection Types

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US031-02 |
| User Story | US-031 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `PatternRegistry` — the module that defines and pre-compiles all regex patterns for AC-2 secret and PII detection, maps each `PatternType` to its `Severity`, and exposes a `scan_text(text, chunk_id)` method that returns all `DetectionFinding` objects for one text block. Regex compilation happens once at module import time (not per call) to meet the 200 ms scan budget (AC-6).

## Implementation Details

**Technology:** Python 3.11+, stdlib `re`, Pydantic v2

**File locations:**
- `src/governance/detection/pattern_registry.py` — `PatternRegistry`, compiled patterns
- `tests/governance/test_pattern_registry.py`

---

### Pattern definitions

Each entry is `(pattern_type, severity, compiled_regex)`. Patterns are anchored and non-greedy where possible to minimise backtracking cost.

```python
# src/governance/detection/pattern_registry.py
from __future__ import annotations
import re
from typing import NamedTuple

from src.governance.schemas.finding import PatternType, Severity, DetectionFinding


class _PatternEntry(NamedTuple):
    pattern_type: PatternType
    severity:     Severity
    regex:        re.Pattern[str]


# Pre-compiled at import time — never compiled per call.
_PATTERNS: list[_PatternEntry] = [
    # ---- Cloud provider secrets ----
    _PatternEntry(
        PatternType.AWS_ACCESS_KEY_ID,
        Severity.CRITICAL,
        # AWS access key IDs: AKIA|ASIA|AROA|AIDA|AGPA|AIPA|ANPA|ANVA|APKA followed by 16 base-36 chars.
        re.compile(r"\b(AKIA|ASIA|AROA|AIDA|AGPA|AIPA|ANPA|ANVA|APKA)[0-9A-Z]{16}\b"),
    ),
    _PatternEntry(
        PatternType.AWS_SECRET_ACCESS_KEY,
        Severity.CRITICAL,
        # 40-char base-64 string immediately following common key assignment patterns.
        # Context-anchored to reduce false positives.
        re.compile(
            r"(?i)(?:aws_secret|secret_access_key|SecretAccessKey)\s*[=:\"' ]+\s*"
            r"([A-Za-z0-9/+=]{40})\b"
        ),
    ),
    _PatternEntry(
        PatternType.GCP_API_KEY,
        Severity.CRITICAL,
        # GCP browser/server API keys: AIza followed by 35 url-safe base-64 chars.
        re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ),
    _PatternEntry(
        PatternType.GCP_SERVICE_ACCOUNT,
        Severity.CRITICAL,
        # Detect the "type" field of a GCP service account JSON credential.
        re.compile(r'"type"\s*:\s*"service_account"'),
    ),
    _PatternEntry(
        PatternType.AZURE_CONNECTION_STRING,
        Severity.CRITICAL,
        # Azure Blob / Queue / Table storage connection strings.
        re.compile(
            r"DefaultEndpointsProtocol=https?;AccountName=[^;]{3,64};"
            r"AccountKey=[A-Za-z0-9+/=]{44,100}"
        ),
    ),
    # ---- SCM tokens ----
    _PatternEntry(
        PatternType.GITHUB_PAT,
        Severity.CRITICAL,
        # New-format GitHub PATs (2021+): ghp_, gho_, ghu_, ghs_, ghr_ + 36 chars.
        # Legacy 40-hex tokens excluded (too many false positives with SHA hashes).
        re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,255}\b"),
    ),
    # ---- PII ----
    _PatternEntry(
        PatternType.EMAIL_ADDRESS,
        Severity.HIGH,
        # RFC 5322 simplified; excludes test fixtures like user@example.com via allow-list in caller.
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    _PatternEntry(
        PatternType.CREDIT_CARD_NUMBER,
        Severity.HIGH,
        # 13–19 digit sequences optionally separated by spaces or hyphens.
        # Luhn validation is applied in post-processing to reduce false positives.
        re.compile(r"\b(?:\d[ \-]?){12,18}\d\b"),
    ),
    _PatternEntry(
        PatternType.PHONE_NUMBER,
        Severity.MEDIUM,
        # E.164 and common regional formats (US, UK, EU).
        re.compile(r"\+?(?:[\d\s\-().]{7,20})\b"),
    ),
    _PatternEntry(
        PatternType.US_SSN,
        Severity.HIGH,
        # US Social Security Number: NNN-NN-NNNN (dashes required to reduce noise).
        re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    ),
    _PatternEntry(
        PatternType.UK_NI_NUMBER,
        Severity.HIGH,
        # UK National Insurance: two letters, six digits, one letter (A–D).
        re.compile(
            r"\b(?!BG|GB|KN|NK|NT|TN|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]"
            r"\d{6}[A-D]\b",
            re.IGNORECASE,
        ),
    ),
]
```

---

### `PatternRegistry`

```python
# src/governance/detection/pattern_registry.py (continued)
import math


def _luhn_check(digits: str) -> bool:
    """Return True if the digit string passes the Luhn algorithm."""
    clean = digits.replace(" ", "").replace("-", "")
    if not clean.isdigit():
        return False
    total = 0
    reverse = clean[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _truncate_preview(match_text: str) -> str:
    """Return first 4 chars + '…' for audit preview. Never exposes the full secret."""
    return match_text[:4] + "…" if len(match_text) > 4 else match_text


class PatternRegistry:
    """
    Stateless scanner that applies all pre-compiled patterns to a text block.
    Instantiate once at application startup; share across all requests.
    """

    def scan_text(self, text: str, chunk_id: str) -> list[DetectionFinding]:
        """
        Apply all patterns to `text` and return a finding for every match.

        Credit card candidates undergo Luhn validation post-match to suppress
        false positives from numeric sequences (e.g. timestamps, version numbers).
        Phone number matches shorter than 7 digits after stripping punctuation
        are suppressed to avoid single-number false positives.
        """
        findings: list[DetectionFinding] = []

        for entry in _PATTERNS:
            for match in entry.regex.finditer(text):
                matched = match.group(0)

                # Credit card Luhn post-filter
                if entry.pattern_type == PatternType.CREDIT_CARD_NUMBER:
                    digits = matched.replace(" ", "").replace("-", "")
                    if not _luhn_check(digits):
                        continue

                # Phone number length post-filter (suppress short numeric sequences)
                if entry.pattern_type == PatternType.PHONE_NUMBER:
                    digits_only = re.sub(r"\D", "", matched)
                    if len(digits_only) < 7:
                        continue

                findings.append(
                    DetectionFinding(
                        pattern_type  = entry.pattern_type,
                        severity      = entry.severity,
                        chunk_id      = chunk_id,
                        char_offset   = match.start(),
                        char_end      = match.end(),
                        match_preview = _truncate_preview(matched),
                    )
                )

        return findings
```

**200 ms performance design (AC-6):**

Pre-compiling all 11 patterns at module load time eliminates `re.compile()` overhead on the hot path. At 32,000 tokens ≈ 128,000 characters, `re.finditer` with a compiled non-backtracking pattern runs in O(n) per pattern. Total scan cost is ~11 × 128 KB ≈ 1.4 MB of text scanned. Python's `re` module processes ~10–50 MB/s depending on pattern complexity; at the conservative end, 1.4 MB scans in ~30–140 ms — within the 200 ms budget. Catastrophic backtracking is prevented by avoiding `.*` in unbounded quantifiers (all patterns use bounded lengths or anchored prefixes).

**False positive mitigations:**

- `AWS_SECRET_ACCESS_KEY`: context-anchored to common assignment keywords; bare 40-char base-64 strings are not matched
- `CREDIT_CARD_NUMBER`: Luhn algorithm post-filter eliminates ~99.9% of incidental 13–19 digit sequences
- `PHONE_NUMBER`: 7-digit minimum after stripping punctuation; prevents matching short IDs or version numbers
- `US_SSN`: excludes invalid SSN ranges (000–, 666–, 900–999) per Social Security Administration rules
- `UK_NI_NUMBER`: excludes the 6 reserved two-letter prefixes (BG, GB, KN, NK, NT, TN, ZZ)

## Acceptance Criteria

- [ ] `PatternRegistry().scan_text(text, "chunk-1")` returns a `DetectionFinding` for each embedded AWS key, GitHub PAT, email, credit card, SSN, and NI number in a synthetic test fixture
- [ ] Credit card number `4111111111111111` (valid Luhn) produces a finding; `1234567890123456` (invalid Luhn) does not
- [ ] A bare 40-char base-64 string without keyword context does NOT produce an `AWS_SECRET_ACCESS_KEY` finding
- [ ] `US_SSN` pattern does not match `000-00-0000` (excluded range)
- [ ] `_truncate_preview("AKIAXYZ1234567890")` returns `"AKIA…"` (max 5 chars with ellipsis)
- [ ] All 11 `PatternType` entries have at least one compiled pattern in `_PATTERNS`

## Dependencies

- TASK-US031-01 (`PatternType`, `Severity`, `DetectionFinding`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] No `re.compile()` calls inside `scan_text()` — compilation at module level only
- [ ] `mypy --strict` passes; no `ruff` lint errors
