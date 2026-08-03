"""PatternRegistry — compiled regex patterns for secret and PII detection.

All patterns are pre-compiled at module import time to avoid per-call
``re.compile()`` overhead and satisfy the 200 ms scan budget (AC-6).
"""
from __future__ import annotations

import re
from typing import NamedTuple

from src.governance.schemas.finding import DetectionFinding, PatternType, Severity


class _PatternEntry(NamedTuple):
    pattern_type: PatternType
    severity: Severity
    regex: re.Pattern[str]


# Pre-compiled at import time — never compiled per call.
_PATTERNS: list[_PatternEntry] = [
    # ---- Cloud provider secrets ----
    _PatternEntry(
        PatternType.AWS_ACCESS_KEY_ID,
        Severity.CRITICAL,
        # AWS access key IDs: AKIA|ASIA|AROA|AIDA|AGPA|AIPA|ANPA|ANVA|APKA + 16 base-36 chars.
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
    _PatternEntry(
        PatternType.GITLAB_PAT,
        Severity.CRITICAL,
        # GitLab Personal Access Tokens: glpat- + 20 chars
        re.compile(r"\bglpat-[0-9A-Za-z_\-]{20,}\b"),
    ),
    _PatternEntry(
        PatternType.BITBUCKET_TOKEN,
        Severity.CRITICAL,
        # Bitbucket app passwords and tokens
        re.compile(r"\b(?:ATBB|ATCTT)[0-9A-Za-z]{32,}\b"),
    ),
    # ---- AI/LLM API keys ----
    _PatternEntry(
        PatternType.OPENAI_API_KEY,
        Severity.CRITICAL,
        # OpenAI API keys: sk-proj- or sk- + alphanumeric
        re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z]{20,}\b"),
    ),
    _PatternEntry(
        PatternType.ANTHROPIC_API_KEY,
        Severity.CRITICAL,
        # Anthropic API keys: sk-ant- + alphanumeric
        re.compile(r"\bsk-ant-[0-9A-Za-z\-_]{95,}\b"),
    ),
    _PatternEntry(
        PatternType.GOOGLE_AI_API_KEY,
        Severity.CRITICAL,
        # Google AI API keys (different from GCP general)
        re.compile(r"\bAI[0-9A-Za-z\-_]{35,}\b"),
    ),
    _PatternEntry(
        PatternType.HUGGINGFACE_TOKEN,
        Severity.CRITICAL,
        # Hugging Face tokens: hf_ + alphanumeric
        re.compile(r"\bhf_[0-9A-Za-z]{32,}\b"),
    ),
    # ---- Generic secrets ----
    _PatternEntry(
        PatternType.GENERIC_API_KEY,
        Severity.HIGH,
        # Generic API key patterns in assignments
        re.compile(
            r"(?i)(?:api[_\-]?key|apikey|api[_\-]token)\s*[=:\"' ]+\s*"
            r"['\"]([A-Za-z0-9_\-]{16,64})['\"]"
        ),
    ),
    _PatternEntry(
        PatternType.GENERIC_SECRET,
        Severity.HIGH,
        # Generic secret patterns
        re.compile(
            r"(?i)(?:secret|password|passwd|pwd)\s*[=:\"' ]+\s*"
            r"['\"]([A-Za-z0-9!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]{8,})['\"]"
        ),
    ),
    _PatternEntry(
        PatternType.BEARER_TOKEN,
        Severity.HIGH,
        # Bearer tokens in Authorization headers
        re.compile(r"(?i)Bearer\s+([A-Za-z0-9_\-\.]{20,})"),
    ),
    _PatternEntry(
        PatternType.JWT_TOKEN,
        Severity.HIGH,
        # JWT tokens: three base64 segments separated by dots
        re.compile(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    ),
    _PatternEntry(
        PatternType.PASSWORD_IN_URL,
        Severity.CRITICAL,
        # Passwords in URLs: protocol://user:password@host
        re.compile(
            r"(?i)(?:https?|ftp|mongodb|postgres|mysql)://[^:]+:([^@]{4,})@"
        ),
    ),
    _PatternEntry(
        PatternType.PRIVATE_KEY,
        Severity.CRITICAL,
        # Private keys (RSA, SSH, PGP)
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    # ---- Database credentials ----
    _PatternEntry(
        PatternType.DATABASE_URL,
        Severity.CRITICAL,
        # Database connection strings
        re.compile(
            r"(?i)(?:postgres|postgresql|mysql|mongodb|redis)://[^:]+:[^@]{4,}@[\w\.\-]+:\d+"
        ),
    ),
    _PatternEntry(
        PatternType.POSTGRES_CONNECTION,
        Severity.CRITICAL,
        # PostgreSQL connection strings
        re.compile(
            r"(?i)(?:host|server)\s*=\s*[\w\.\-]+.+(?:password|pwd)\s*=\s*[^\s;]+"
        ),
    ),
    _PatternEntry(
        PatternType.MONGODB_CONNECTION,
        Severity.CRITICAL,
        # MongoDB connection strings
        re.compile(r"mongodb(?:\+srv)?://[^:]+:[^@]{4,}@[\w\.\-]+"),
    ),
    # ---- Vault/HashiCorp ----
    _PatternEntry(
        PatternType.VAULT_TOKEN,
        Severity.CRITICAL,
        # Vault tokens: hvs. or s. prefix
        re.compile(r"\b(?:hvs|s)\.[0-9A-Za-z]{24,}\b"),
    ),
    # ---- Slack ----
    _PatternEntry(
        PatternType.SLACK_TOKEN,
        Severity.CRITICAL,
        # Slack tokens: xoxb-, xoxp-, xoxa-, xoxr-
        re.compile(r"\bxox[bpra]-[0-9]{10,13}-[0-9]{10,13}-[0-9A-Za-z]{24,}\b"),
    ),
    _PatternEntry(
        PatternType.SLACK_WEBHOOK,
        Severity.HIGH,
        # Slack webhook URLs
        re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]{8,}/B[A-Z0-9]{8,}/[A-Za-z0-9]{24,}"),
    ),
    # ---- PII ----
    _PatternEntry(
        PatternType.EMAIL_ADDRESS,
        Severity.HIGH,
        # RFC 5322 simplified.
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    _PatternEntry(
        PatternType.CREDIT_CARD_NUMBER,
        Severity.HIGH,
        # 13–19 digit sequences optionally separated by spaces or hyphens.
        # Luhn validation applied as a post-filter.
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
    _PatternEntry(
        PatternType.IP_ADDRESS,
        Severity.LOW,
        # IPv4 addresses
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
            r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        ),
    ),
]


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
    return match_text[:4] + "\u2026" if len(match_text) > 4 else match_text


class PatternRegistry:
    """Stateless scanner that applies all pre-compiled patterns to a text block.

    Instantiate once at application startup and share across all requests.
    No ``re.compile()`` calls occur inside ``scan_text``; all compilation
    happens at module import time.
    """

    def scan_text(self, text: str, chunk_id: str) -> list[DetectionFinding]:
        """Apply all patterns to ``text`` and return a finding for every match.

        Post-filters applied:
        - Credit card candidates undergo Luhn validation to suppress false positives.
        - Phone number matches with fewer than 7 digits are suppressed.
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

                # Phone number length post-filter
                if entry.pattern_type == PatternType.PHONE_NUMBER:
                    digits_only = re.sub(r"\D", "", matched)
                    if len(digits_only) < 7:
                        continue

                findings.append(
                    DetectionFinding(
                        pattern_type=entry.pattern_type,
                        severity=entry.severity,
                        chunk_id=chunk_id,
                        char_offset=match.start(),
                        char_end=match.end(),
                        match_preview=_truncate_preview(matched),
                    )
                )

        return findings
