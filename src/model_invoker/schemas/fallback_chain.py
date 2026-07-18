"""Fallback chain schemas for multi-candidate model invocation (TASK-US020-01)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FallbackChain(BaseModel):
    """Ordered list of model IDs to try, primary first."""

    model_config = ConfigDict(frozen=True)

    model_ids: list[str] = Field(min_length=1)
    intent_type: str


class InvocationFailure(BaseModel):
    """Returned when all fallback attempts are exhausted."""

    model_config = ConfigDict(frozen=True)

    message: str  # human-readable; surfaced to API caller
    attempts: int  # number of models tried (≤ MAX_FALLBACK_ATTEMPTS + 1)
    last_error_code: str  # final RetryableErrorCode value
    tried_model_ids: list[str]
