"""BoilerplateDetector — filters chunks matched by any active boilerplate rule."""

from __future__ import annotations

import re

from src.compression.boilerplate.rules import DEFAULT_RULES, BoilerplateRule
from src.compression.schemas.removed_chunk import RemovalReason, RemovedChunk
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


class BoilerplateDetector:
    """Tests chunk content against compiled boilerplate regex rules.

    All patterns are pre-compiled at construction time so the hot loop
    performs only ``pattern.search(content)`` calls.
    """

    def __init__(self, rules: list[BoilerplateRule] | None = None) -> None:
        active = [r for r in (rules or DEFAULT_RULES) if r.enabled]
        self._compiled: list[tuple[str, re.Pattern[str]]] = [
            (rule.name, re.compile(rule.pattern, re.IGNORECASE | re.MULTILINE))
            for rule in active
        ]

    def matching_rule(self, content: str) -> str | None:
        """Return the name of the first matching rule, or None."""
        for rule_name, pattern in self._compiled:
            if pattern.search(content):
                return rule_name
        return None

    def filter(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[list[RetrievedChunk], list[RemovedChunk]]:
        """Partition chunks into kept and removed sets.

        Returns:
            A tuple of (kept_chunks, removed_chunks). Removed chunks carry an
            audit record with the matching rule name and original content.
        """
        kept: list[RetrievedChunk] = []
        removed: list[RemovedChunk] = []
        for chunk in chunks:
            rule_name = self.matching_rule(chunk.content)
            if rule_name:
                removed.append(
                    RemovedChunk(
                        chunk_id=chunk.chunk_id,
                        source_id=chunk.source_id,
                        reason=RemovalReason.BOILERPLATE,
                        boilerplate_rule=rule_name,
                        original_content=chunk.content,
                    )
                )
            else:
                kept.append(chunk)
        return kept, removed
