"""ContextRedactor — replaces critical/high findings with [REDACTED:<type>] placeholders.

Pure function — no I/O. Safe for unit testing without mocking.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from src.governance.schemas.finding import DetectionFinding, GovernanceScanResult

_PLACEHOLDER_TEMPLATE = "[REDACTED:{type}]"


class RedactionResult(BaseModel):
    """Pair of (redacted text, count of substitutions) for one chunk."""

    model_config = ConfigDict(frozen=True)

    original_chunk_id: str
    redacted_text: str
    substitutions_made: int
    # True if the text was changed from the original.
    was_redacted: bool


class ContextRedactor:
    """Pure function — no I/O.

    Replaces critical/high findings with [REDACTED:<type>] placeholders
    (AC-4, AC-5). Medium findings are recorded in GovernanceScanResult
    but left in place.

    Approach: sort findings for each chunk by char_offset DESCENDING,
    then substitute from right to left. This preserves earlier character
    offsets across successive substitutions so no finding needs adjustment.
    """

    def redact_context(
        self,
        context_items: list[dict],
        scan_result: GovernanceScanResult,
    ) -> tuple[list[dict], list[RedactionResult]]:
        """Return (updated_context_items, list[RedactionResult]).

        Only findings with severity in (critical, high) are redacted (AC-4).
        Medium findings are recorded in GovernanceScanResult but left in place.
        Context items without any redaction-eligible findings are returned unchanged.
        """
        # Group findings by chunk_id for O(1) lookup per chunk
        findings_by_chunk: dict[str, list[DetectionFinding]] = defaultdict(list)
        for f in scan_result.findings:
            if f.requires_redaction:
                findings_by_chunk[f.chunk_id].append(f)

        updated_items: list[dict] = []
        redaction_results: list[RedactionResult] = []

        for idx, item in enumerate(context_items):
            chunk_id = str(item.get("chunk_id") or item.get("id") or idx)
            findings = findings_by_chunk.get(chunk_id, [])

            if not findings:
                updated_items.append(item)
                continue

            text = item.get("text") or ""
            redacted = self._apply_redactions(text, findings)

            updated_item = {**item, "text": redacted}
            updated_items.append(updated_item)
            redaction_results.append(
                RedactionResult(
                    original_chunk_id=chunk_id,
                    redacted_text=redacted,
                    substitutions_made=len(findings),
                    was_redacted=redacted != text,
                )
            )

        return updated_items, redaction_results

    def _apply_redactions(
        self,
        text: str,
        findings: list[DetectionFinding],
    ) -> str:
        """Apply substitutions in reverse offset order to preserve earlier positions.

        Overlapping findings are handled by skipping any finding whose range is
        fully contained within an already-processed range.
        """
        # Sort descending by char_offset so right-to-left substitution is safe
        sorted_findings = sorted(findings, key=lambda f: f.char_offset, reverse=True)

        result = text
        processed_end = len(text)

        for f in sorted_findings:
            # Skip if this finding's range overlaps an already-processed range
            if f.char_end > processed_end:
                continue
            placeholder = _PLACEHOLDER_TEMPLATE.format(type=f.pattern_type.value)
            result = result[: f.char_offset] + placeholder + result[f.char_end :]
            processed_end = f.char_offset

        return result
