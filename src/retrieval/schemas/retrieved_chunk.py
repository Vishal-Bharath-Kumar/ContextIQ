"""Canonical chunk schema produced by every search path (Qdrant ANN, OpenSearch BM25)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChunkMetadata(BaseModel):
    """Source-document provenance attached to every retrieved chunk."""

    file_path: str
    timestamp: datetime
    author: str
    url: str | None = None
    chunk_index: int | None = None


class RetrievedChunk(BaseModel):
    """Single retrieval result shared by all search paths and downstream nodes."""

    chunk_id: str = Field(
        description="Stable content-addressable ID: sha256(source_id + file_path + chunk_index)[:16]"
    )
    source_id: str = Field(
        description="Connector/store identifier, e.g. 'github', 'confluence'."
    )
    content: str = Field(description="Raw text of the chunk.")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Normalised relevance score in [0.0, 1.0].",
    )
    metadata: ChunkMetadata
    search_mode: Literal["vector", "keyword", "rrf"] = "rrf"

    # US-014 additions — pre-merge per-signal scores (None when not available)
    vector_score: float | None = None  # cosine similarity from Qdrant (before RRF)
    keyword_score: float | None = None  # normalised BM25 score from OpenSearch (before RRF)

    # US-017 additions — LLM summarisation metadata
    compressed: bool = False
    # Token count of the original content before LLM summarisation.
    # None when the chunk has never been summarised.
    original_token_count: int | None = None

    model_config = ConfigDict(frozen=True)


def make_chunk_id(source_id: str, file_path: str, chunk_index: int) -> str:
    """Return a 16-hex-char content-addressable ID for a chunk."""
    raw = f"{source_id}:{file_path}:{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
