"""AgentState TypedDict and ExecutionStatus enum for the LangGraph pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, TypedDict

from src.agents.schemas.execution_plan import ExecutionPlan
from src.agents.schemas.intent import IntentType
from src.governance.opa.schemas import PolicyDecision
from src.governance.schemas.finding import DetectionFinding
from src.knowledge_graph.traversal.schemas import GraphContextItem


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

    # ── Compression trace fields (TASK-US034-04) ───────────────────────
    ranked_context_pre_compression: NotRequired[list[dict] | None]  # pre-compression snapshot
    compression_tokens_before: NotRequired[int | None]              # aliased from tokens_before_compression
    compression_tokens_after: NotRequired[int | None]               # aliased from tokens_after_compression

    # ── Governance output (EP-010) ─────────────────────────────────────
    governance_decisions: list[dict] | None  # allow/deny per chunk
    redacted_chunks: list[str] | None  # chunk IDs that were redacted
    # New fields added by governance_node (TASK-US031-04):
    governance_findings: NotRequired[list[DetectionFinding]]
    context_redacted: NotRequired[bool]
    governance_scan_ms: NotRequired[float]
    governance_blocked: NotRequired[bool]  # True when fail-safe timeout blocked the scan
    governance_summary: NotRequired[dict | None]  # Comprehensive governance summary with risk scoring

    # ── OPA filter output (TASK-US032-04) ─────────────────────────────
    jwt_claims: NotRequired[dict]  # decoded JWT claims; read by opa_filter_node
    tenant_id: NotRequired[str]  # tenant identifier forwarded from JWT middleware
    team_id: NotRequired[str | None]  # team extracted from JWT claims by gateway middleware
    opa_decisions: NotRequired[list]  # PolicyDecision objects from opa_filter_node
    opa_denied_count: NotRequired[int]  # number of chunks denied in the OPA pass
    opa_bundle_version: NotRequired[str]  # OPA bundle version at evaluation time

    # ── Audit trace (AC-7) ─────────────────────────────────────────────
    execution_trace: NotRequired[list[dict]]  # append-only per-node audit entries

    # ── Execution Replay trace (TASK-US034-04) ─────────────────────────
    trace_id: NotRequired[str | None]          # str(UUID) set at pipeline entry
    trace_object_key: NotRequired[str | None]  # populated by trace_writer_node after dispatch
    trace_written: NotRequired[bool]           # True once _persist_trace task is enqueued

    # ── Model routing output (EP-006) ──────────────────────────────────
    selected_model: str | None
    model_routing_score: float | None
    final_response: dict | None

    # ── Knowledge Graph expansion output (EP-009) ──────────────────────
    graph_context_items: NotRequired[list[GraphContextItem]]
    graph_traversal_skipped: NotRequired[bool]
    graph_tokens_used: NotRequired[int]

    # ── OPA authorization output (US-032) ──────────────────────────────
    opa_decisions: NotRequired[list[PolicyDecision]]
    opa_denied_count: NotRequired[int]
    opa_bundle_version: NotRequired[str]

    # ── LLM cost output (TASK-US037-03) ────────────────────────────────
    llm_cost_usd: NotRequired[float | None]  # populated by llm_metrics_node

    # ── OTel tracing (TASK-US038-02) ───────────────────────────────────
    _otel_ctx: NotRequired[object | None]  # RootSpanContext — not serialised to JSON
    otel_trace_id: NotRequired[str | None]  # 32-char hex trace ID = request_id without hyphens
