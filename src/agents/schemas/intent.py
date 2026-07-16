"""Intent classification schema models for the ContextIQ pipeline (EP-003)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class IntentType(StrEnum):
    DEBUGGING = "debugging"
    CODE_GEN = "code-gen"
    ARCHITECTURE = "architecture"
    DOCS = "docs"
    INCIDENT = "incident"
    METRICS = "metrics"
    CODE_REVIEW = "code-review"
    GENERAL = "general"


class IntentResult(BaseModel):
    intent_type: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
