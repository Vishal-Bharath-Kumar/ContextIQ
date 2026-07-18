"""Unit tests for ExactDeduplicator and content_fingerprint (TASK-US015-02)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.compression.dedup.exact_deduplicator import (
    ExactDeduplicator,
    _normalise,
    content_fingerprint,
)
from src.compression.schemas.removed_chunk import RemovalReason, RemovedChunk
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _meta(file_path: str = "a/b.py") -> ChunkMetadata:
    return ChunkMetadata(file_path=file_path, timestamp=_TS, author="tester")


def _chunk(
    chunk_id: str,
    content: str,
    source_id: str = "github",
    score: float = 0.9,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        content=content,
        score=score,
        metadata=_meta(),
    )


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_strips_leading_trailing_whitespace(self) -> None:
        assert _normalise("  hello  ") == "hello"

    def test_collapses_horizontal_whitespace(self) -> None:
        assert _normalise("a  b\t\tc") == "a b c"

    def test_collapses_excessive_blank_lines(self) -> None:
        result = _normalise("a\n\n\n\nb")
        assert result == "a\n\nb"

    def test_preserves_single_blank_line(self) -> None:
        assert _normalise("a\n\nb") == "a\n\nb"

    def test_empty_string(self) -> None:
        assert _normalise("") == ""

    def test_whitespace_only(self) -> None:
        assert _normalise("   \t\n  ") == ""


# ---------------------------------------------------------------------------
# content_fingerprint
# ---------------------------------------------------------------------------


class TestContentFingerprint:
    def test_returns_16_char_hex(self) -> None:
        fp = content_fingerprint("hello")
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic_same_input(self) -> None:
        assert content_fingerprint("abc") == content_fingerprint("abc")

    def test_different_content_different_fingerprint(self) -> None:
        assert content_fingerprint("abc") != content_fingerprint("xyz")

    def test_normalisation_applied_trailing_whitespace(self) -> None:
        assert content_fingerprint("hello  ") == content_fingerprint("hello")

    def test_normalisation_applied_extra_blank_lines(self) -> None:
        assert content_fingerprint("a\n\n\nb") == content_fingerprint("a\n\nb")

    def test_fingerprint_is_sha256_based(self) -> None:
        import hashlib

        expected = hashlib.sha256(b"hello").hexdigest()[:16]
        assert content_fingerprint("hello") == expected


# ---------------------------------------------------------------------------
# ExactDeduplicator.deduplicate
# ---------------------------------------------------------------------------


class TestExactDeduplicator:
    def setup_method(self) -> None:
        self.dedup = ExactDeduplicator()

    # --- all unique ----------------------------------------------------------

    def test_all_unique_returns_empty_removed(self) -> None:
        chunks = [
            _chunk("c1", "content alpha"),
            _chunk("c2", "content beta"),
            _chunk("c3", "content gamma"),
        ]
        kept, removed = self.dedup.deduplicate(chunks)
        assert kept == chunks
        assert removed == []

    def test_empty_input(self) -> None:
        kept, removed = self.dedup.deduplicate([])
        assert kept == []
        assert removed == []

    # --- two identical chunks ------------------------------------------------

    def test_two_identical_chunks_keeps_first(self) -> None:
        c1 = _chunk("c1", "def foo(): pass", score=0.9)
        c2 = _chunk("c2", "def foo(): pass", score=0.5)
        kept, removed = self.dedup.deduplicate([c1, c2])
        assert kept == [c1]
        assert len(removed) == 1
        assert removed[0].chunk_id == "c2"
        assert removed[0].duplicate_of == "c1"

    def test_removed_reason_is_exact_duplicate(self) -> None:
        c1 = _chunk("c1", "same content")
        c2 = _chunk("c2", "same content")
        _, removed = self.dedup.deduplicate([c1, c2])
        assert removed[0].reason == RemovalReason.EXACT_DUPLICATE

    # --- three chunks, one duplicate ----------------------------------------

    def test_three_chunks_one_duplicate(self) -> None:
        c1 = _chunk("c1", "alpha")
        c2 = _chunk("c2", "beta")
        c3 = _chunk("c3", "alpha")  # duplicate of c1
        kept, removed = self.dedup.deduplicate([c1, c2, c3])
        assert [ch.chunk_id for ch in kept] == ["c1", "c2"]
        assert len(removed) == 1
        assert removed[0].chunk_id == "c3"
        assert removed[0].duplicate_of == "c1"

    # --- whitespace normalisation dedup -------------------------------------

    def test_trailing_whitespace_treated_as_duplicate(self) -> None:
        c1 = _chunk("c1", "def foo(): pass")
        c2 = _chunk("c2", "def foo(): pass   \n")
        kept, removed = self.dedup.deduplicate([c1, c2])
        assert len(kept) == 1
        assert kept[0].chunk_id == "c1"
        assert len(removed) == 1

    def test_extra_blank_lines_treated_as_duplicate(self) -> None:
        c1 = _chunk("c1", "line one\n\nline two")
        c2 = _chunk("c2", "line one\n\n\n\nline two")
        kept, removed = self.dedup.deduplicate([c1, c2])
        assert len(kept) == 1
        assert len(removed) == 1

    def test_extra_horizontal_whitespace_treated_as_duplicate(self) -> None:
        c1 = _chunk("c1", "hello world")
        c2 = _chunk("c2", "hello  world")
        kept, removed = self.dedup.deduplicate([c1, c2])
        assert len(kept) == 1
        assert len(removed) == 1

    # --- cross-source dedup -------------------------------------------------

    def test_cross_source_duplicate_keeps_higher_score(self) -> None:
        c_github = _chunk("gh1", "shared content", source_id="github", score=0.8)
        c_confluence = _chunk("cf1", "shared content", source_id="confluence", score=0.6)
        kept, removed = self.dedup.deduplicate([c_github, c_confluence])
        assert len(kept) == 1
        assert kept[0].source_id == "github"
        assert removed[0].source_id == "confluence"
        assert removed[0].duplicate_of == "gh1"

    def test_removed_chunk_preserves_original_content(self) -> None:
        content = "def foo(): pass"
        c1 = _chunk("c1", content)
        c2 = _chunk("c2", content)
        _, removed = self.dedup.deduplicate([c1, c2])
        assert removed[0].original_content == content

    # --- input list not mutated ---------------------------------------------

    def test_does_not_mutate_input(self) -> None:
        c1 = _chunk("c1", "alpha")
        c2 = _chunk("c2", "alpha")
        original = [c1, c2]
        snapshot = list(original)
        self.dedup.deduplicate(original)
        assert original == snapshot

    # --- multiple duplicates ------------------------------------------------

    def test_multiple_duplicates_of_same_chunk(self) -> None:
        c1 = _chunk("c1", "repeated")
        c2 = _chunk("c2", "repeated")
        c3 = _chunk("c3", "repeated")
        kept, removed = self.dedup.deduplicate([c1, c2, c3])
        assert len(kept) == 1
        assert kept[0].chunk_id == "c1"
        assert len(removed) == 2
        assert all(r.duplicate_of == "c1" for r in removed)

    def test_removed_chunks_are_removed_chunk_instances(self) -> None:
        c1 = _chunk("c1", "same")
        c2 = _chunk("c2", "same")
        _, removed = self.dedup.deduplicate([c1, c2])
        assert all(isinstance(r, RemovedChunk) for r in removed)
