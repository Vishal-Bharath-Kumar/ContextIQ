"""Clarification question schema for the ContextIQ pipeline (EP-003 / TASK-US011-01)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClarificationQuestion(BaseModel):
    question: str = Field(
        description="One focused question ≤ 50 words that resolves prompt ambiguity.",
        max_length=300,  # hard cap on raw string length as a secondary guard
    )
