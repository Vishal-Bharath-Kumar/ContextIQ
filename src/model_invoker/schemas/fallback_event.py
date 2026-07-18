"""FallbackEvent schema — structured log record emitted per fallback attempt (US-020 AC-4)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.model_invoker.error_classifier import RetryableErrorCode


class FallbackEvent(BaseModel):
    """Structured log record emitted per fallback attempt (US-020 AC-4)."""

    model_config = ConfigDict(frozen=True)

    attempt: int  # 1-based; 1 = first fallback after primary failure
    primary_model_id: str  # model that failed
    error_code: RetryableErrorCode
    fallback_model_id: str | None  # next model to be tried; None if chain exhausted
    provider: str  # extracted from model_id (prefix before '/')
