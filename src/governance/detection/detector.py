"""SecretPIIDetector — scans ranked-context chunks for secrets and PII.

Raises GovernanceScanTimeoutError when the 200 ms budget is exceeded
(fail-safe: prevents unscanned context from reaching the LLM).
"""
from __future__ import annotations

import logging
import time

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.governance.detection.pattern_registry import PatternRegistry
from src.governance.schemas.finding import (
    DetectionFinding,
    GovernanceScanResult,
    PatternType,
)

logger = logging.getLogger(__name__)

_REGISTRY = PatternRegistry()  # singleton — one instance per process


class DetectorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOVERNANCE_DETECTOR_",
        env_file=".env",
        extra="ignore",
    )

    # Hard budget in milliseconds; governance_node raises GovernanceScanTimeoutError
    # if exceeded (fail-safe: block context from reaching LLM).
    scan_timeout_ms: float = 200.0
    # Domains exempt from EMAIL_ADDRESS detection (e.g. internal test domains).
    # Applied as a post-filter on EMAIL_ADDRESS findings.
    email_allow_domains: list[str] = []


class GovernanceScanTimeoutError(RuntimeError):
    """Raised when the scan budget is exhausted.

    Triggers a fail-safe block in governance_node — it is safer to surface
    an error to the user than to forward potentially sensitive content.
    """


class SecretPIIDetector:
    """Scans context chunks for secrets and PII via PatternRegistry."""

    def __init__(self, settings: DetectorSettings | None = None) -> None:
        self._settings = settings or DetectorSettings()

    def scan_context(self, context_items: list[dict]) -> GovernanceScanResult:
        """Scan all context chunks for secrets and PII.

        Each item in context_items must have:
          - "text": str          — the chunk text to scan
          - "chunk_id": str | None — provenance ID (falls back to list index if absent)

        Raises GovernanceScanTimeoutError if total scan time exceeds scan_timeout_ms.
        This is intentional: a timeout must block the context from reaching the LLM
        rather than silently skipping the governance check (fail-safe design).
        """
        start: float = time.monotonic()
        all_findings: list[DetectionFinding] = []

        for idx, item in enumerate(context_items):
            # Check budget before each chunk (early exit on timeout)
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > self._settings.scan_timeout_ms:
                raise GovernanceScanTimeoutError(
                    f"Governance scan exceeded {self._settings.scan_timeout_ms} ms budget "
                    f"after {idx} chunks (elapsed: {elapsed_ms:.1f} ms)"
                )

            text = item.get("text") or ""
            chunk_id = str(item.get("chunk_id") or item.get("id") or idx)
            findings = _REGISTRY.scan_text(text, chunk_id)

            # Apply email allow-list post-filter
            if self._settings.email_allow_domains:
                findings = [
                    f
                    for f in findings
                    if not (
                        f.pattern_type == PatternType.EMAIL_ADDRESS
                        and any(
                            text[f.char_offset : f.char_end].endswith(domain)
                            for domain in self._settings.email_allow_domains
                        )
                    )
                ]

            all_findings.extend(findings)

        duration_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "SecretPIIDetector: scanned %d chunks, found %d findings in %.1f ms",
            len(context_items),
            len(all_findings),
            duration_ms,
        )
        return GovernanceScanResult.build(
            findings=all_findings,
            chunks_scanned=len(context_items),
            scan_duration_ms=duration_ms,
        )
