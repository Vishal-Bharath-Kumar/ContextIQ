"""Admin-configurable settings for the semantic deduplication stage."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SEMANTIC_SIMILARITY_THRESHOLD: float = 0.92  # US-016 AC-2: retain when similarity >= this value
SEMANTIC_EMBED_BATCH_SIZE: int = 64  # max chunks per fastembed batch call


class SemanticDedupSettings(BaseSettings):
    """Admin-configurable parameters for semantic deduplication.

    Environment variables:
        SEMANTIC_DEDUP_THRESHOLD   — float in (0.0, 1.0], default 0.92
        SEMANTIC_DEDUP_BATCH_SIZE  — int >= 1, default 64
    """

    threshold: float = Field(default=SEMANTIC_SIMILARITY_THRESHOLD, gt=0.0, le=1.0)
    batch_size: int = Field(default=SEMANTIC_EMBED_BATCH_SIZE, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="SEMANTIC_DEDUP_",
        env_file=".env",
        extra="ignore",
    )


_settings: SemanticDedupSettings | None = None


def get_semantic_dedup_settings() -> SemanticDedupSettings:
    """Return the module-level singleton instance of SemanticDedupSettings."""
    global _settings
    if _settings is None:
        _settings = SemanticDedupSettings()
    return _settings
