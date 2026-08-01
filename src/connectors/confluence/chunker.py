"""
ConfluencePageChunker — token-aware page splitter for Confluence content.

TASK-US023-04: ConfluencePageChunker and ConfluenceConnector.sync().

Pages exceeding TOKEN_CHUNK_THRESHOLD (10 000 tokens) are split at natural
section boundaries (Markdown headings produced by strip_confluence_storage).
Oversized headingless sections are hard-split at token boundaries.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from src.llm.token_encoding import get_cl100k_encoding

TOKEN_CHUNK_THRESHOLD = 10_000  # US-023 AC-6: pages above this are chunked

# Heading patterns in plain text produced by strip_confluence_storage()
_HEADING_RE = re.compile(r"\n(?=#{1,3} |\n[A-Z][^\n]{3,80}\n[=-]{3,})")

_ENCODER = get_cl100k_encoding()


class PageChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_id: str
    chunk_index: int  # 0-based ordinal within the page
    content: str
    token_count: int
    heading: str | None  # first heading in this chunk, if detected


class ConfluencePageChunker:
    """
    Splits a Confluence page into token-bounded chunks at natural section boundaries.
    Pages under TOKEN_CHUNK_THRESHOLD are returned as a single chunk.
    """

    def chunk(self, page_id: str, plain_text: str) -> list[PageChunk]:
        tokens = _ENCODER.encode(plain_text)
        if len(tokens) <= TOKEN_CHUNK_THRESHOLD:
            return [
                PageChunk(
                    page_id=page_id,
                    chunk_index=0,
                    content=plain_text,
                    token_count=len(tokens),
                    heading=self._extract_heading(plain_text),
                )
            ]

        return self._split_at_headings(page_id, plain_text)

    def _split_at_headings(self, page_id: str, text: str) -> list[PageChunk]:
        """
        Split at heading boundaries; merge short sections to keep
        chunks close to but not exceeding TOKEN_CHUNK_THRESHOLD.
        """
        sections = _HEADING_RE.split(text)
        chunks: list[PageChunk] = []
        buffer = ""

        for section in sections:
            candidate = (buffer + "\n" + section).strip() if buffer else section.strip()
            if len(_ENCODER.encode(candidate)) > TOKEN_CHUNK_THRESHOLD:
                if buffer:
                    chunks.append(self._make_chunk(page_id, len(chunks), buffer))
                # Hard-split oversized section at token boundary
                for hard_chunk in self._hard_split(page_id, len(chunks), section):
                    chunks.append(hard_chunk)
                buffer = ""
            else:
                buffer = candidate

        if buffer:
            chunks.append(self._make_chunk(page_id, len(chunks), buffer))

        return chunks or [
            PageChunk(
                page_id=page_id,
                chunk_index=0,
                content=text[:5000],
                token_count=len(_ENCODER.encode(text[:5000])),
                heading=None,
            )
        ]

    def _hard_split(self, page_id: str, base_index: int, text: str) -> list[PageChunk]:
        """Token-boundary split for oversized sections with no heading markers."""
        tokens = _ENCODER.encode(text)
        chunks = []
        for i in range(0, len(tokens), TOKEN_CHUNK_THRESHOLD):
            slice_tokens = tokens[i : i + TOKEN_CHUNK_THRESHOLD]
            content = _ENCODER.decode(slice_tokens)
            chunks.append(self._make_chunk(page_id, base_index + len(chunks), content))
        return chunks

    def _make_chunk(self, page_id: str, index: int, content: str) -> PageChunk:
        return PageChunk(
            page_id=page_id,
            chunk_index=index,
            content=content,
            token_count=len(_ENCODER.encode(content)),
            heading=self._extract_heading(content),
        )

    @staticmethod
    def _extract_heading(text: str) -> str | None:
        m = re.search(r"^#{1,3} (.+)$", text, re.MULTILINE)
        return m.group(1).strip() if m else None
