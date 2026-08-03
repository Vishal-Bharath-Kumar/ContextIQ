"""Exact-duplicate deduplicator for the AI Compression Engine (EP-005 / US-015)."""

from __future__ import annotations

import hashlib
import re

from src.compression.schemas.removed_chunk import RemovalReason, RemovedChunk
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


def _normalise(text: str) -> str:
    """Strip leading/trailing whitespace and collapse internal whitespace runs.

    Normalisation makes fingerprinting robust to trivial formatting differences
    (trailing newlines, mixed indentation) without altering semantic content.
    """
    text = text.strip()
    text = re.sub(r"[ \t]+", " ", text)     # collapse horizontal whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse excessive blank lines
    return text


def content_fingerprint(text: str) -> str:
    """Return a 16-char hex SHA-256 of the normalised content."""
    return hashlib.sha256(_normalise(text).encode()).hexdigest()[:16]


class ExactDeduplicator:
    """Remove exact-duplicate chunks by SHA-256 content fingerprint.

    The first occurrence of a fingerprint (highest-ranked, as input is
    pre-sorted descending by score) is always retained; subsequent duplicates
    are recorded in the ``RemovedChunk`` audit list.
    """

    def deduplicate(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[list[RetrievedChunk], list[RemovedChunk]]:
        """Remove exact-duplicate chunks by content fingerprint.

        The first occurrence (highest-ranked, as input is pre-sorted by score)
        is always retained; subsequent duplicates are removed.

        Returns:
            A tuple of ``(kept_chunks, removed_chunks)``.  The input list is
            never mutated.
        """
        seen_fingerprints: dict[str, str] = {}  # fingerprint → retained chunk_id
        kept: list[RetrievedChunk] = []
        removed: list[RemovedChunk] = []

        for chunk in chunks:
            fp = content_fingerprint(chunk.content)
            if fp in seen_fingerprints:
                removed.append(
                    RemovedChunk(
                        chunk_id=chunk.chunk_id,
                        source_id=chunk.source_id,
                        reason=RemovalReason.EXACT_DUPLICATE,
                        duplicate_of=seen_fingerprints[fp],
                        original_content=chunk.content,
                    )
                )
            else:
                seen_fingerprints[fp] = chunk.chunk_id
                kept.append(chunk)

        return kept, removed
