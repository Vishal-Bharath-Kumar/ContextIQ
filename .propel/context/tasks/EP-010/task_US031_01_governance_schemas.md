# TASK-US031-01 — Governance Schemas: `PatternType`, `Severity`, `DetectionFinding`, `GovernanceScanResult`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US031-01 |
| User Story | US-031 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Done |

## Description

Define the Pydantic schemas used across the governance pipeline: `PatternType` (all detectable secret/PII categories), `Severity` (critical/high/medium), `DetectionFinding` (a single match with offset and chunk provenance), and `GovernanceScanResult` (wrapper for a full context scan). These are the data contracts shared by `SecretPIIDetector` (TASK-US031-02/03), `ContextRedactor` (TASK-US031-03), and `governance_node()` (TASK-US031-04). They also lay the schema foundation for US-032's OPA enforcement layer, which extends the same `GovernanceScanResult`.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2

**File locations:**
- `src/governance/schemas/finding.py` — `PatternType`, `Severity`, `DetectionFinding`, `GovernanceScanResult`
- `tests/governance/test_finding_schema.py`

---

### `PatternType` and `Severity`

```python
# src/governance/schemas/finding.py
from __future__ import annotations
from enum   import StrEnum
from uuid   import UUID
from pydantic import BaseModel, ConfigDict, Field


class PatternType(StrEnum):
    # Cloud provider secrets
    AWS_ACCESS_KEY_ID       = "AWS_ACCESS_KEY_ID"
    AWS_SECRET_ACCESS_KEY   = "AWS_SECRET_ACCESS_KEY"
    GCP_API_KEY             = "GCP_API_KEY"
    GCP_SERVICE_ACCOUNT     = "GCP_SERVICE_ACCOUNT"
    AZURE_CONNECTION_STRING = "AZURE_CONNECTION_STRING"
    # SCM tokens
    GITHUB_PAT              = "GITHUB_PAT"
    # PII
    EMAIL_ADDRESS           = "EMAIL_ADDRESS"
    CREDIT_CARD_NUMBER      = "CREDIT_CARD_NUMBER"
    PHONE_NUMBER            = "PHONE_NUMBER"
    US_SSN                  = "US_SSN"
    UK_NI_NUMBER            = "UK_NI_NUMBER"


class Severity(StrEnum):
    CRITICAL = "critical"   # credentials that enable direct cloud/SCM access
    HIGH     = "high"       # PII that constitutes personal data under GDPR/CCPA
    MEDIUM   = "medium"     # lower-risk PII (phone numbers, generic emails)
```

---

### `DetectionFinding`

```python
# src/governance/schemas/finding.py (continued)

class DetectionFinding(BaseModel):
    """Immutable record of a single regex match within a context chunk."""
    model_config = ConfigDict(frozen=True)

    pattern_type:   PatternType
    severity:       Severity
    # UUID of the context chunk where the match was found (AC-3).
    chunk_id:       str = Field(
        description="Context chunk identifier; may be a UUID string or a connector-native ID.",
    )
    # Character offset of the match start within the chunk text (AC-3).
    char_offset:    int = Field(ge=0)
    # Character offset of the match end (exclusive).
    char_end:       int = Field(ge=0)
    # Truncated preview of the matched text, max 8 chars.
    # Never stores the full secret — only enough for debugging.
    match_preview:  str = Field(
        description="First 4 chars + '...' of match. Used for audit log; never logs the full value.",
        max_length=16,
    )

    @property
    def requires_redaction(self) -> bool:
        """True for critical and high severity findings (AC-4)."""
        return self.severity in (Severity.CRITICAL, Severity.HIGH)


class GovernanceScanResult(BaseModel):
    """Output of a full context scan across all chunks."""
    model_config = ConfigDict(frozen=True)

    findings:        list[DetectionFinding]
    # Number of chunks scanned; useful for audit rate calculation.
    chunks_scanned:  int = Field(ge=0)
    # Wall-clock scan duration in milliseconds; validated against 200 ms SLA.
    scan_duration_ms: float = Field(ge=0.0)
    # True if any critical or high severity findings were found (convenience flag).
    has_critical_or_high: bool

    @classmethod
    def build(
        cls,
        findings:         list[DetectionFinding],
        chunks_scanned:   int,
        scan_duration_ms: float,
    ) -> "GovernanceScanResult":
        critical_or_high = any(f.requires_redaction for f in findings)
        return cls(
            findings          = findings,
            chunks_scanned    = chunks_scanned,
            scan_duration_ms  = scan_duration_ms,
            has_critical_or_high = critical_or_high,
        )
```

---

### Severity assignment rationale

| Pattern type | Severity | Rationale |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | CRITICAL | Direct cloud credential, enables lateral movement |
| `AWS_SECRET_ACCESS_KEY` | CRITICAL | Must accompany access key to authenticate |
| `GCP_API_KEY` | CRITICAL | Unrestricted GCP API key grants broad access |
| `GCP_SERVICE_ACCOUNT` | CRITICAL | JSON blob contains private key |
| `AZURE_CONNECTION_STRING` | CRITICAL | Contains account key granting full storage access |
| `GITHUB_PAT` | CRITICAL | Full repository access including private repos |
| `EMAIL_ADDRESS` | HIGH | Personal data under GDPR Art. 4 |
| `CREDIT_CARD_NUMBER` | HIGH | PCI-DSS scope; serious regulatory liability |
| `US_SSN` | HIGH | US identity theft risk; HIPAA-adjacent |
| `UK_NI_NUMBER` | HIGH | UK identity data; ICO reportable |
| `PHONE_NUMBER` | MEDIUM | Personal data; lower exploitation risk alone |

## Acceptance Criteria

- [x] `DetectionFinding.requires_redaction` returns `True` for `CRITICAL` and `HIGH`, `False` for `MEDIUM`
- [x] `GovernanceScanResult.build()` sets `has_critical_or_high=True` when any finding is critical/high
- [x] `GovernanceScanResult.build()` sets `has_critical_or_high=False` when all findings are medium
- [x] All 11 `PatternType` values and 3 `Severity` values are present in their respective enums
- [x] `DetectionFinding` is frozen (`ConfigDict(frozen=True)`)
- [x] `match_preview` max length is 16 characters (enforced by Pydantic `max_length`)
- [x] `mypy --strict` passes

## Dependencies

None — this is the foundational schema task.

## Definition of Done

- [x] Code reviewed and merged to `main`
- [x] `mypy --strict` passes; no `ruff` lint errors
