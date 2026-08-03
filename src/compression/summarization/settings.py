"""Admin-configurable settings for the LLM-based chunk summarisation stage."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SUMMARIZATION_TOKEN_THRESHOLD: int = 500  # US-017 AC-1: chunks above this are summarised
SUMMARIZATION_TARGET_RATIO: float = 0.40  # target: summary ≤ 40% of original tokens (60% reduction)
SUMMARIZATION_MAX_OUTPUT_TOKENS: int = 400  # LLM max_tokens cap — prevents runaway cost


class SummarizationSettings(BaseSettings):
    """Configuration for LLM-based chunk summarisation.

    Environment variables (all prefixed SUMMARIZATION_):
        TOKEN_THRESHOLD     — int ≥ 1, default 500
        MODEL_NAME          — string, default "ollama/llama3.2"
                              Set to a model-router endpoint when EP-006 is available.
        TARGET_RATIO        — float in (0.0, 1.0), default 0.40
        MAX_OUTPUT_TOKENS   — int ≥ 50, default 400
        MAX_CONCURRENT      — int ≥ 1, default 10 (asyncio.gather concurrency cap)
        LANGFUSE_ENABLED    — bool, default True
    """

    token_threshold: int = Field(default=SUMMARIZATION_TOKEN_THRESHOLD, ge=1)
    model_name: str = Field(default="ollama/llama3.2")
    target_ratio: float = Field(default=SUMMARIZATION_TARGET_RATIO, gt=0.0, lt=1.0)
    max_output_tokens: int = Field(default=SUMMARIZATION_MAX_OUTPUT_TOKENS, ge=50)
    max_concurrent: int = Field(default=10, ge=1)
    langfuse_enabled: bool = Field(default=True)
    timeout_s: float = Field(default=30.0, gt=0.0)

    model_config = SettingsConfigDict(
        env_prefix="SUMMARIZATION_",
        env_file=".env",
        extra="ignore",
    )


_settings: SummarizationSettings | None = None


def get_summarization_settings() -> SummarizationSettings:
    """Return the module-level singleton instance of SummarizationSettings."""
    global _settings
    if _settings is None:
        _settings = SummarizationSettings()
    return _settings
