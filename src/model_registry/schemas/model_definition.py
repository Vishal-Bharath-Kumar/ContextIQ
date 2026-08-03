"""Canonical Pydantic types for the Model Capability Registry.

Shared contract for API endpoints, the service layer, the Redis cache,
and the Dynamic Model Router (US-019).
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LatencyTier(StrEnum):
    FAST = "fast"      # p95 < 500 ms (e.g. gpt-4o-mini, claude-haiku)
    MEDIUM = "medium"  # p95 500 ms – 2 s (e.g. gpt-4o)
    SLOW = "slow"      # p95 > 2 s (e.g. o1, deep-reasoning models)


class ModelCapability(StrEnum):
    CHAT = "chat"                    # conversational turn completion
    COMPLETION = "completion"        # single-turn text generation
    EMBEDDING = "embedding"          # vector embedding output
    CODE = "code"                    # code-optimised generation
    SUMMARIZATION = "summarization"  # long-text compression
    VISION = "vision"                # image + text input
    FUNCTION_CALL = "function_call"  # tool/function calling support


_MODEL_ID_RE = re.compile(r"[a-zA-Z0-9._\-/:]+")


class ModelRegistration(BaseModel):
    """Inbound API payload for registering a new model."""

    model_id: str = Field(
        min_length=1,
        max_length=128,
        description="Unique identifier, e.g. 'gpt-4o-mini' or 'anthropic/claude-3-haiku'",
    )
    provider: str = Field(min_length=1, max_length=64)
    context_window: int = Field(gt=0, description="Max tokens in context window")
    cost_per_1k_tokens: float = Field(
        ge=0.0,
        description="USD per 1 000 tokens (combined input+output average)",
    )
    latency_tier: LatencyTier
    capabilities: list[ModelCapability] = Field(min_length=1)
    is_active: bool = True

    @field_validator("model_id")
    @classmethod
    def model_id_url_safe(cls, v: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9._\-/:]+", v):
            raise ValueError(
                "model_id must contain only alphanumeric, '.', '_', '-', '/', ':' characters"
            )
        return v


class ModelDefinition(ModelRegistration):
    """Stored and returned representation of a registered model."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)  # SQLAlchemy ORM → Pydantic
