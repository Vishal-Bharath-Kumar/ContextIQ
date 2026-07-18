"""RuleBasedCompressor — orchestrates exact dedup then boilerplate removal (EP-005 / US-015)."""

from __future__ import annotations

from src.compression.boilerplate.detector import BoilerplateDetector
from src.compression.boilerplate.settings import BoilerplateSettings
from src.compression.dedup.exact_deduplicator import ExactDeduplicator
from src.compression.schemas.removed_chunk import RemovedChunk
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


class RuleBasedCompressor:
    """Orchestrate rule-based compression: exact deduplication then boilerplate removal.

    This is the sole entry point consumed by ``compression_node`` (TASK-US015-05).
    Injecting custom ``deduplicator`` / ``detector`` instances is supported for
    unit testing and advanced configuration.
    """

    def __init__(
        self,
        deduplicator: ExactDeduplicator | None = None,
        detector: BoilerplateDetector | None = None,
    ) -> None:
        settings = BoilerplateSettings()
        self._deduplicator = deduplicator or ExactDeduplicator()
        self._detector = detector or BoilerplateDetector(rules=settings.get_rules())

    def compress(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[list[RetrievedChunk], list[RemovedChunk]]:
        """Apply rule-based compression: exact dedup → boilerplate removal.

        Steps applied in order:
          1. Exact deduplication (content fingerprint)
          2. Boilerplate pattern filtering

        Returns:
            A tuple of ``(compressed_chunks, all_removed_chunks)``.  Removed
            chunks are ordered: exact-duplicate removals first, then boilerplate
            removals.  The compressed list preserves the relative order of the
            input (no resorting).
        """
        if not chunks:
            return [], []

        # Step 1: exact deduplication — O(n), eliminates chunks before regex scan
        after_dedup, dedup_removed = self._deduplicator.deduplicate(chunks)

        # Step 2: boilerplate removal — runs on the already-reduced set
        after_boilerplate, boiler_removed = self._detector.filter(after_dedup)

        all_removed = dedup_removed + boiler_removed
        return after_boilerplate, all_removed
