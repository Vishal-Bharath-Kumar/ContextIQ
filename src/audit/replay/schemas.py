"""Pydantic API response DTOs for the Replay Explorer — TASK-US035-01.

Consumed by:
  - Replay API routes (TASK-US035-02)
  - Angular components (TASK-US035-03/04)
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.audit.trace.schemas import (
    CompressionDelta,
    ExecutionTrace,
    GovernanceDecisionSummary,
    RetrievedChunkSummary,
)


class TraceListItem(BaseModel):
    """One row in the Replay Explorer search results table (AC-1)."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    user_id: str
    timestamp: datetime
    intent: str
    model_selected: str | None = None
    governance_blocked: bool = False
    opa_denied_count: int = 0
    object_key: str  # MinIO pointer — used for detail fetch


class TraceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TraceListItem]
    total: int
    limit: int
    offset: int


class TimelineStep(BaseModel):
    """
    One entry in the step-by-step pipeline timeline (AC-2 / AC-3).
    Maps from ExecutionPlanStep with display-friendly fields.
    """

    model_config = ConfigDict(frozen=True)

    step_number: int
    node: str
    eval_ms: float | None = None
    metadata: dict = Field(default_factory=dict)  # type: ignore[type-arg]


class TraceDetailResponse(BaseModel):
    """
    Full trace detail for the detail view (AC-3).
    Fields:
      - intent_classification  → intent (AC-3)
      - retrieved_sources      → chunks with relevance scores (AC-3)
      - compression_delta      → before/after token counts (AC-3)
      - governance_decisions   → allows/denies (AC-3)
      - model_selected         → selected model (AC-3)
      - response_summary       → response summary (AC-3)
      - timeline               → step-by-step pipeline (AC-2)
    """

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    user_id: str
    timestamp: datetime
    latency_ms: float | None = None

    # AC-3 fields
    intent_classification: str
    intent_confidence: float | None = None
    retrieved_sources: list[RetrievedChunkSummary]
    compression_delta: CompressionDelta | None = None
    governance_decisions: GovernanceDecisionSummary
    model_selected: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    response_summary: str | None = None

    # AC-2: step-by-step pipeline timeline
    timeline: list[TimelineStep]

    # Raw trace available for export (AC-6); not serialised in list responses
    _raw_trace: ExecutionTrace | None = None
