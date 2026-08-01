"""Offline-safe token encoding helpers.

Uses ``tiktoken`` when the ``cl100k_base`` encoding is locally available and
falls back to a deterministic character-based encoder when the encoding cannot
be loaded in restricted environments.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

import tiktoken


class EncodingProtocol(Protocol):
    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: list[int]) -> str: ...


class _CharacterFallbackEncoding:
    """Deterministic fallback used when ``tiktoken`` cannot load its vocabulary."""

    def encode(self, text: str) -> list[int]:
        return [ord(char) for char in text]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


@lru_cache(maxsize=1)
def get_cl100k_encoding() -> EncodingProtocol:
    """Return a reusable encoding object without requiring network access."""
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return _CharacterFallbackEncoding()