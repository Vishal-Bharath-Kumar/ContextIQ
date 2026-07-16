"""AgentState TypedDict and ExecutionStatus enum for the LangGraph pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from src.agents.schemas.execution_plan import ExecutionPlan
from src.agents.schemas.intent import IntentType


class DegradedSourceInfo(TypedDict):
    """Metadata for a connector that failed during retrieval or governance."""

    source_id: str
    error_type: str
    message: str


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class AgentState(TypedDict):
    # ── Identity (set at init, immutable) ──────────────────────────────
    request_id: str  # UUID v4
    user_id: str  # JWT sub claim
    username: str
    roles: list[str]
    tool_name: str  # MCP tool that triggered this request
    prompt: str  # raw user prompt
    timestamp: str  # ISO-8601 UTC

    # ── Pipeline status ────────────────────────────────────────────────
    status: ExecutionStatus
    current_node: str  # name of the node currently executing
    error: str | None

    # ── Intent detection output (EP-003) ──────────────────────────────
    intent_type: IntentType | None
    intent_confidence: float | None
    intent_source_list: list[str] | None  # source keys derived in TASK-US009-03
    execution_plan: ExecutionPlan | None  # token budgets, source list, ranking strategy
    requires_clarification: bool | None  # True when confidence < INTENT_CONFIDENCE_THRESHOLD
    clarification_question: str | None  # the generated question text (TASK-US011-01)
    clarification_round: int  # 0 on first pass; incremented to 1 before second-pass re-entry

    # ── Retrieval output (EP-004) ──────────────────────────────────────
    raw_context: list[dict] | None  # pre-compression chunks
    ranked_context: list[dict] | None  # post-ranking chunks
    degraded_sources: list[DegradedSourceInfo] | None  # failed connectors from retrieval

    # ── Compression output (EP-005) ────────────────────────────────────
    compressed_context: list[dict] | None
    tokens_before_compression: int | None
    tokens_after_compression: int | None

    # ── Governance output (EP-010) ─────────────────────────────────────
    governance_decisions: list[dict] | None  # allow/deny per chunk
    redacted_chunks: list[str] | None  # chunk IDs that were redacted

    # ── Model routing output (EP-006) ──────────────────────────────────
    selected_model: str | None
    model_routing_score: float | None
    final_response: dict | None
