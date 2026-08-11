"""Pydantic DTOs for AI execution traces — TASK-US034-01.

These schemas are the single source of truth shared by:
  - MinIO writer        (TASK-US034-02)
  - Index repository    (TASK-US034-03)
  - Trace writer node   (TASK-US034-04)
  - Replay Explorer     (US-035)

All root models are frozen (immutable) per AC-2.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ------------------------------------------------------------------ #
# Sub-structures (AC-2 field breakdown)                               #
# ------------------------------------------------------------------ #


class RetrievedChunkSummary(BaseModel):
    """Lightweight summary of a single retrieved context chunk."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_id: str
    relevance_score: float
    classification_label: str = "internal"
    redacted: bool = False  # True if governance_node applied redaction
    opa_denied: bool = False  # True if opa_filter_node denied this chunk


class CompressionDelta(BaseModel):
    """Token counts before and after compression (for US-035 detail view)."""

    model_config = ConfigDict(frozen=True)

    tokens_before: int
    tokens_after: int
    chunks_before: int
    chunks_after: int

    @property
    def reduction_pct(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return round(100 * (1 - self.tokens_after / self.tokens_before), 1)


class GovernanceDecisionSummary(BaseModel):
    """Condensed governance and OPA filter outcomes for the trace."""

    model_config = ConfigDict(frozen=True)

    findings_count: int = 0
    redacted_count: int = 0
    opa_denied_count: int = 0
    opa_bundle_version: str = "unknown"
    governance_blocked: bool = False


class ExecutionPlanStep(BaseModel):
    """One entry in the execution_trace list from AgentState (AC-2)."""

    model_config = ConfigDict(frozen=True)

    node: str
    eval_ms: float | None = None
    metadata: dict = Field(default_factory=dict)  # type: ignore[type-arg]


# ------------------------------------------------------------------ #
# Root trace document written to MinIO and indexed in PostgreSQL      #
# ------------------------------------------------------------------ #


class ExecutionTrace(BaseModel):
    """Immutable execution trace — one document per request.

    All fields map to AC-2 required properties:
      request_id, user_id, timestamp, prompt, intent,
      execution_plan, retrieved_chunks (pre + post compression),
      governance_decisions, model_selected, response_summary.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    request_id: UUID
    tenant_id: str
    user_id: str  # sub claim from JWT
    user_roles: list[str] = Field(default_factory=list)

    # Timing (AC-2: timestamp)
    timestamp: datetime
    latency_ms: float | None = None

    # Content (AC-2: prompt, intent)
    prompt: str
    intent: str  # classification result, e.g. "technical_support"

    # Pipeline steps (AC-2: execution_plan)
    execution_plan: list[ExecutionPlanStep] = Field(default_factory=list)

    # Retrieval (AC-2: retrieved_chunks pre- and post-compression)
    retrieved_chunks_pre_compression: list[RetrievedChunkSummary] = Field(
        default_factory=list
    )
    retrieved_chunks_post_compression: list[RetrievedChunkSummary] = Field(
        default_factory=list
    )
    compression_delta: CompressionDelta | None = None

    # Governance (AC-2: governance_decisions)
    governance_decisions: GovernanceDecisionSummary = Field(
        default_factory=GovernanceDecisionSummary
    )

    # Model routing (AC-2: model_selected)
    model_selected: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    # Output (AC-2: response_summary)
    response_summary: str | None = None  # first 500 chars of the model response

    # Object store location (populated after MinIO write)
    object_key: str | None = None
    object_version: str | None = None


class TraceIndexEntry(BaseModel):
    """Columns written to PostgreSQL for search (AC-4).

    Subset of ExecutionTrace; excludes large text fields.
    """

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    tenant_id: str
    user_id: str
    timestamp: datetime
    intent: str
    model_selected: str | None = None
    governance_blocked: bool = False
    opa_denied_count: int = 0
    object_key: str = ""
    object_version: str = ""
