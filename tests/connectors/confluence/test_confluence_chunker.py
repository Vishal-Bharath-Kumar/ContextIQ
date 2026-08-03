"""
Unit tests for TASK-US023-04: ConfluencePageChunker.

Coverage targets:
  - chunk() returns a single PageChunk when page is <= 10 000 tokens
  - chunk() returns multiple chunks when page exceeds 10 000 tokens
  - each chunk has token_count <= TOKEN_CHUNK_THRESHOLD
  - chunk_index is 0-based and sequential across all returned chunks
  - heading is extracted when present in chunk text
  - heading is None when no heading pattern found
  - _hard_split is invoked for oversized headingless sections
  - fallback single chunk returned when split yields empty list
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.connectors.confluence.chunker import (
    _ENCODER,
    TOKEN_CHUNK_THRESHOLD,
    ConfluencePageChunker,
    PageChunk,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAGE_ID = "page-001"


def _tokens_for(text: str) -> int:
    return len(_ENCODER.encode(text))


def _make_text_of_tokens(n: int) -> str:
    """Return a plain-text string whose token count is approximately n."""
    # "word " encodes to ~1 token; repeat until we overshoot then trim
    unit = "word "
    result = unit * (n + 10)
    tokens = _ENCODER.encode(result)
    return _ENCODER.decode(tokens[:n])


def _make_headed_text_of_tokens(n: int, heading: str = "# Section Alpha") -> str:
    """Return text starting with a heading whose total token count is approximately n."""
    body = _make_text_of_tokens(n - _tokens_for(heading + "\n"))
    return f"{heading}\n{body}"


# ---------------------------------------------------------------------------
# Short-page tests (single chunk path)
# ---------------------------------------------------------------------------


class TestShortPage:
    def test_returns_single_chunk_for_short_text(self) -> None:
        chunker = ConfluencePageChunker()
        text = "Hello world"
        result = chunker.chunk(PAGE_ID, text)
        assert len(result) == 1
        chunk = result[0]
        assert chunk.page_id == PAGE_ID
        assert chunk.chunk_index == 0
        assert chunk.content == text
        assert chunk.token_count == _tokens_for(text)

    def test_single_chunk_at_exact_threshold(self) -> None:
        chunker = ConfluencePageChunker()
        text = _make_text_of_tokens(TOKEN_CHUNK_THRESHOLD)
        result = chunker.chunk(PAGE_ID, text)
        assert len(result) == 1
        assert result[0].chunk_index == 0
        assert result[0].token_count <= TOKEN_CHUNK_THRESHOLD

    def test_heading_extracted_from_short_page(self) -> None:
        chunker = ConfluencePageChunker()
        text = "# My Heading\nSome content here."
        result = chunker.chunk(PAGE_ID, text)
        assert result[0].heading == "My Heading"

    def test_heading_none_when_absent(self) -> None:
        chunker = ConfluencePageChunker()
        text = "No heading in this page, just plain text."
        result = chunker.chunk(PAGE_ID, text)
        assert result[0].heading is None

    def test_empty_text_returns_single_chunk(self) -> None:
        chunker = ConfluencePageChunker()
        result = chunker.chunk(PAGE_ID, "")
        assert len(result) == 1
        assert result[0].chunk_index == 0


# ---------------------------------------------------------------------------
# Long-page tests (multi-chunk path)
# ---------------------------------------------------------------------------


class TestLongPage:
    def test_long_page_returns_multiple_chunks(self) -> None:
        chunker = ConfluencePageChunker()
        # Build ~3x the threshold of text with heading boundaries
        section_tokens = TOKEN_CHUNK_THRESHOLD + 500
        section_a = _make_headed_text_of_tokens(section_tokens, "# Section A")
        section_b = _make_headed_text_of_tokens(section_tokens, "# Section B")
        section_c = _make_headed_text_of_tokens(section_tokens, "# Section C")
        text = "\n".join([section_a, section_b, section_c])
        result = chunker.chunk(PAGE_ID, text)
        assert len(result) > 1

    def test_all_chunks_below_threshold(self) -> None:
        chunker = ConfluencePageChunker()
        section_tokens = TOKEN_CHUNK_THRESHOLD + 200
        parts = [_make_headed_text_of_tokens(section_tokens, f"# Sect {i}") for i in range(3)]
        text = "\n".join(parts)
        result = chunker.chunk(PAGE_ID, text)
        for chunk in result:
            assert chunk.token_count <= TOKEN_CHUNK_THRESHOLD, (
                f"chunk {chunk.chunk_index} exceeds threshold: {chunk.token_count}"
            )

    def test_chunk_indexes_are_sequential(self) -> None:
        chunker = ConfluencePageChunker()
        section_tokens = TOKEN_CHUNK_THRESHOLD + 200
        parts = [_make_headed_text_of_tokens(section_tokens, f"# S{i}") for i in range(3)]
        text = "\n".join(parts)
        result = chunker.chunk(PAGE_ID, text)
        for expected_idx, chunk in enumerate(result):
            assert chunk.chunk_index == expected_idx

    def test_all_chunks_carry_correct_page_id(self) -> None:
        chunker = ConfluencePageChunker()
        section_tokens = TOKEN_CHUNK_THRESHOLD + 200
        parts = [_make_headed_text_of_tokens(section_tokens, f"# H{i}") for i in range(3)]
        text = "\n".join(parts)
        result = chunker.chunk(PAGE_ID, text)
        for chunk in result:
            assert chunk.page_id == PAGE_ID

    def test_heading_extracted_in_multi_chunk(self) -> None:
        chunker = ConfluencePageChunker()
        section_tokens = TOKEN_CHUNK_THRESHOLD + 200
        text = _make_headed_text_of_tokens(section_tokens * 2, "# Main Heading")
        result = chunker.chunk(PAGE_ID, text)
        # At least the first chunk should contain the heading
        headings = [c.heading for c in result if c.heading]
        assert len(headings) >= 1


# ---------------------------------------------------------------------------
# Hard-split tests (oversized headingless sections)
# ---------------------------------------------------------------------------


class TestHardSplit:
    def test_hard_split_invoked_for_oversized_headingless_section(self) -> None:
        chunker = ConfluencePageChunker()
        # Single large headingless block — no heading markers anywhere
        big_text = _make_text_of_tokens(TOKEN_CHUNK_THRESHOLD * 2 + 100)
        result = chunker.chunk(PAGE_ID, big_text)
        assert len(result) >= 2
        for chunk in result:
            assert chunk.token_count <= TOKEN_CHUNK_THRESHOLD

    def test_hard_split_chunk_indexes_sequential(self) -> None:
        chunker = ConfluencePageChunker()
        big_text = _make_text_of_tokens(TOKEN_CHUNK_THRESHOLD * 2 + 100)
        result = chunker.chunk(PAGE_ID, big_text)
        for expected_idx, chunk in enumerate(result):
            assert chunk.chunk_index == expected_idx


# ---------------------------------------------------------------------------
# PageChunk immutability
# ---------------------------------------------------------------------------


class TestPageChunkModel:
    def test_page_chunk_is_frozen(self) -> None:
        chunk = PageChunk(
            page_id="p1",
            chunk_index=0,
            content="text",
            token_count=1,
            heading=None,
        )
        with pytest.raises(ValidationError):
            chunk.content = "modified"  # type: ignore[misc]
