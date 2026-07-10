# TASK-US031-03 — `SecretPIIDetector` and `ContextRedactor`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US031-03 |
| User Story | US-031 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `SecretPIIDetector` — the component that scans all ranked-context chunks via `PatternRegistry` and returns a `GovernanceScanResult` within 200 ms (AC-6). Implement `ContextRedactor` — the component that replaces critical/high findings with `[REDACTED:<type>]` placeholders (AC-4, AC-5), handling overlapping matches safely. Both are pure functions with no I/O, so they can be exercised in tests without mocking.

## Implementation Details

**Technology:** Python 3.11+, stdlib `re`, `time`, Pydantic v2

**File locations:**
- `src/governance/detection/detector.py` — `SecretPIIDetector`, `DetectorSettings`
- `src/governance/detection/redactor.py` — `ContextRedactor`, `RedactionResult`
- `tests/governance/test_detector.py`
- `tests/governance/test_redactor.py`

---

### `DetectorSettings`

```python
# src/governance/detection/detector.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class DetectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOVERNANCE_DETECTOR_", env_file=".env")

    # Hard budget in milliseconds; governance_node raises GovernanceScanTimeoutError
    # if exceeded (fail-safe: block context from reaching LLM).
    scan_timeout_ms: float = 200.0
    # Domains exempt from EMAIL_ADDRESS detection (e.g. internal test domains).
    # Applied as a post-filter on EMAIL_ADDRESS findings.
    email_allow_domains: list[str] = []
```

---

### `SecretPIIDetector`

```python
# src/governance/detection/detector.py (continued)
import time
import logging
from src.governance.detection.pattern_registry import PatternRegistry
from src.governance.schemas.finding            import (
    DetectionFinding, GovernanceScanResult, PatternType,
)

logger = logging.getLogger(__name__)

_REGISTRY = PatternRegistry()   # singleton — one instance per process


class GovernanceScanTimeoutError(RuntimeError):
    """Raised when the scan budget is exhausted. Triggers a fail-safe block in governance_node."""


class SecretPIIDetector:
    def __init__(self, settings: DetectorSettings | None = None) -> None:
        self._settings = settings or DetectorSettings()

    def scan_context(self, context_items: list[dict]) -> GovernanceScanResult:
        """
        Scan all context chunks for secrets and PII.

        Each item in context_items must have:
          - "text": str   — the chunk text to scan
          - "chunk_id": str | None  — provenance ID (falls back to list index if absent)

        Raises GovernanceScanTimeoutError if total scan time exceeds scan_timeout_ms.
        This is intentional: a timeout must block the context from reaching the LLM
        rather than silently skipping the governance check (fail-safe design).
        """
        start    = time.monotonic()
        all_findings: list[DetectionFinding] = []

        for idx, item in enumerate(context_items):
            # Check budget before each chunk (early exit on timeout)
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > self._settings.scan_timeout_ms:
                raise GovernanceScanTimeoutError(
                    f"Governance scan exceeded {self._settings.scan_timeout_ms} ms budget "
                    f"after {idx} chunks (elapsed: {elapsed_ms:.1f} ms)"
                )

            text     = item.get("text") or ""
            chunk_id = str(item.get("chunk_id") or item.get("id") or idx)
            findings = _REGISTRY.scan_text(text, chunk_id)

            # Apply email allow-list post-filter
            if self._settings.email_allow_domains:
                findings = [
                    f for f in findings
                    if not (
                        f.pattern_type == PatternType.EMAIL_ADDRESS
                        and any(
                            f.match_preview.endswith(domain)
                            for domain in self._settings.email_allow_domains
                        )
                    )
                ]

            all_findings.extend(findings)

        duration_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "SecretPIIDetector: scanned %d chunks, found %d findings in %.1f ms",
            len(context_items), len(all_findings), duration_ms,
        )
        return GovernanceScanResult.build(
            findings         = all_findings,
            chunks_scanned   = len(context_items),
            scan_duration_ms = duration_ms,
        )
```

---

### `RedactionResult`

```python
# src/governance/detection/redactor.py
from pydantic import BaseModel, ConfigDict

class RedactionResult(BaseModel):
    """Pair of (redacted text, count of substitutions) for one chunk."""
    model_config = ConfigDict(frozen=True)

    original_chunk_id:     str
    redacted_text:         str
    substitutions_made:    int
    # True if the text was changed from the original.
    was_redacted:          bool
```

---

### `ContextRedactor`

```python
# src/governance/detection/redactor.py (continued)
from src.governance.schemas.finding import DetectionFinding, GovernanceScanResult

_PLACEHOLDER_TEMPLATE = "[REDACTED:{type}]"


class ContextRedactor:
    """
    Pure function — no I/O. Replaces critical/high findings with
    [REDACTED:<type>] placeholders (AC-4, AC-5).

    Approach: sort findings for each chunk by char_offset DESCENDING,
    then substitute from right to left. This preserves earlier character
    offsets across successive substitutions so no finding needs adjustment.
    """

    def redact_context(
        self,
        context_items: list[dict],
        scan_result:   GovernanceScanResult,
    ) -> tuple[list[dict], list[RedactionResult]]:
        """
        Return (updated_context_items, list[RedactionResult]).

        Only findings with severity in (critical, high) are redacted (AC-4).
        Medium findings are recorded in GovernanceScanResult but left in place.
        Context items without any redaction-eligible findings are returned unchanged.
        """
        # Group findings by chunk_id for O(1) lookup per chunk
        from collections import defaultdict
        findings_by_chunk: dict[str, list[DetectionFinding]] = defaultdict(list)
        for f in scan_result.findings:
            if f.requires_redaction:
                findings_by_chunk[f.chunk_id].append(f)

        updated_items:     list[dict]            = []
        redaction_results: list[RedactionResult] = []

        for idx, item in enumerate(context_items):
            chunk_id = str(item.get("chunk_id") or item.get("id") or idx)
            findings = findings_by_chunk.get(chunk_id, [])

            if not findings:
                updated_items.append(item)
                continue

            text     = item.get("text") or ""
            redacted = self._apply_redactions(text, findings)

            updated_item = {**item, "text": redacted}
            updated_items.append(updated_item)
            redaction_results.append(
                RedactionResult(
                    original_chunk_id  = chunk_id,
                    redacted_text      = redacted,
                    substitutions_made = len(findings),
                    was_redacted       = redacted != text,
                )
            )

        return updated_items, redaction_results

    def _apply_redactions(
        self,
        text:     str,
        findings: list[DetectionFinding],
    ) -> str:
        """
        Apply substitutions in reverse offset order to preserve earlier positions.
        Overlapping findings are handled by skipping any finding whose range is
        fully contained within an already-processed range.
        """
        # Sort descending by char_offset so right-to-left substitution is safe
        sorted_findings = sorted(findings, key=lambda f: f.char_offset, reverse=True)

        result        = text
        processed_end = len(text)

        for f in sorted_findings:
            # Skip if this finding's range is already inside a processed range
            if f.char_end > processed_end:
                continue
            placeholder = _PLACEHOLDER_TEMPLATE.format(type=f.pattern_type.value)
            result      = result[: f.char_offset] + placeholder + result[f.char_end :]
            processed_end = f.char_offset

        return result
```

**Overlap handling rationale:**

When two patterns overlap (e.g. an email address inside a URL that also matches a phone pattern), sorting by descending offset and tracking `processed_end` ensures that the rightmost match is replaced first, then the pointer moves left. A finding that extends past `processed_end` has already been subsumed by a prior substitution and is skipped — preventing double-redaction corruption.

**Fail-safe on timeout (AC-6):**

`SecretPIIDetector.scan_context()` raises `GovernanceScanTimeoutError` if the budget is exceeded. The `governance_node()` (TASK-US031-04) catches this exception and **blocks** context delivery to the LLM rather than silently passing unscanned content. This is a deliberate fail-safe: it is safer to surface an error to the user than to forward potentially sensitive content.

## Acceptance Criteria

- [ ] `ContextRedactor._apply_redactions()` replaces `AKIA1234567890ABCD` with `[REDACTED:AWS_ACCESS_KEY_ID]`
- [ ] Placeholder format is exactly `[REDACTED:<UPPER_CASE_TYPE>]` — e.g. `[REDACTED:EMAIL_ADDRESS]`
- [ ] Medium severity findings (`PHONE_NUMBER`) are NOT redacted from context text
- [ ] Overlapping findings produce no garbled output — only the outermost (rightmost) is redacted
- [ ] `SecretPIIDetector.scan_context()` with a synthetic 32 000-token (≈128 KB) text completes in < 200 ms
- [ ] `GovernanceScanTimeoutError` is raised (not swallowed) when the budget is exceeded
- [ ] `redact_context()` is a pure function: it does not mutate any input list or dict in place

## Dependencies

- TASK-US031-01 (`DetectionFinding`, `GovernanceScanResult`, `Severity`, `PatternType`)
- TASK-US031-02 (`PatternRegistry`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Performance test validates < 200 ms for 128 KB synthetic text with all 11 pattern types active
- [ ] `mypy --strict` passes; no `ruff` lint errors
