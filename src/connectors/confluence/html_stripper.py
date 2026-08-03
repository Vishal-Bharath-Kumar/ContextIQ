"""
html_stripper — plain-text extraction from Confluence storage-format XML/HTML.

TASK-US023-03: Results Mapping and Plain-Text Extraction.

Confluence storage format embeds proprietary XML namespaces (ac:*, ri:*).
This module strips all markup and returns human-readable text suitable for
the EP-008 indexing pipeline.
"""
from __future__ import annotations

from html.parser import HTMLParser


class _PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_tags = {"style", "script", "ac:parameter", "ac:default-parameter", "ac:structured-macro"}
        self._skip_depth: int = 0  # handles nested skip tags correctly

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def plain_text(self) -> str:
        return " ".join(self._parts)


def strip_confluence_storage(html: str) -> str:
    """
    Convert Confluence storage-format XML/HTML to plain text.

    Returns at most 5 000 characters of readable content.
    Tags listed in ``_skip_tags`` (and their children) are dropped entirely.
    All other tag content is concatenated with whitespace separators.
    """
    extractor = _PlainTextExtractor()
    extractor.feed(html)
    return extractor.plain_text()[:5000]
