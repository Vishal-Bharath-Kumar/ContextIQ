"""Removed-chunk audit schema used by the compression pipeline (EP-005)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from src.retrieval.schemas.retrieved_chunk import RetrievedChunk  # noqa: F401 — re-exported


class RemovalReason(StrEnum):
    EXACT_DUPLICATE = "exact_duplicate"  # identical content fingerprint
    BOILERPLATE = "boilerplate"  # matched a configured regex rule
    SEMANTIC_NEAR_DUP = "semantic_near_dup"  # cosine similarity ≥ threshold (US-016)


class RemovedChunk(BaseModel):
    """Audit record for a chunk excluded from the final context set.

    ``original_content`` is preserved for EP-011 replay traces and must NOT be
    forwarded to the model as part of the compressed context.
    """

    chunk_id: str
    source_id: str
    reason: RemovalReason
    duplicate_of: str | None = None  # chunk_id of the retained duplicate (if applicable)
    boilerplate_rule: str | None = None  # regex rule name that matched (if applicable)
    original_content: str  # full text preserved for replay — NOT sent to model

    model_config = ConfigDict(frozen=True)
