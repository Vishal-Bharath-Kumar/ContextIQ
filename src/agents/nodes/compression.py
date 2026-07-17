"""Stub compression node — implemented in EP-005."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from src.agents.state import AgentState, ExecutionStatus
from src.observability.cost.compression_metrics import CompressionMetricsRecorder
from src.observability.cost.schemas import CompressionRecord
from src.observability.tracing.node_span import otel_node_span

logger = logging.getLogger(__name__)


@otel_node_span("compression.context_window")
async def compression_node(state: AgentState) -> AgentState:
    # Preserve pre-compression context before any truncation (for trace AC-2)
    pre_compression_context = list(state.get("ranked_context") or [])

    # --- NEW instrumentation block (US-037 AC-2) ---
    tokens_before: int = state.get("tokens_before_compression") or 0
    tokens_after: int = state.get("tokens_after_compression") or 0
    jwt_claims: dict[str, Any] = state.get("jwt_claims") or {}
    groups: list[str] = jwt_claims.get("groups") or ["default"]
    comp_rec = CompressionRecord(
        request_id=_get_request_id(state),
        tenant_id=state.get("tenant_id") or "default",
        user_id=jwt_claims.get("sub") or "anonymous",
        team_id=jwt_claims.get("team_id") or groups[0],
        intent_type=str(state.get("intent_type") or "unknown"),
        timestamp=datetime.now(tz=UTC),
        tokens_before_compression=tokens_before,
        tokens_after_compression=tokens_after,
    )
    recorder = _get_compression_recorder(state)
    if recorder is not None:
        recorder.record(comp_rec)
    else:
        logger.warning("compression_recorder not configured; skipping compression metrics")
    # --- END instrumentation block ---

    return {
        **state,
        "current_node": "compression_agent",
        "status": ExecutionStatus.RUNNING,
        "ranked_context_pre_compression": pre_compression_context,  # NEW — for trace AC-2
        "compression_tokens_before": state.get("tokens_before_compression"),  # NEW
        "compression_tokens_after": state.get("tokens_after_compression"),    # NEW
    }


# ------------------------------------------------------------------ #
# Injectable singletons (set during lifespan startup)                 #
# ------------------------------------------------------------------ #

_DEFAULT_COMPRESSION_RECORDER: CompressionMetricsRecorder | None = None


def set_compression_recorder(recorder: CompressionMetricsRecorder) -> None:
    global _DEFAULT_COMPRESSION_RECORDER
    _DEFAULT_COMPRESSION_RECORDER = recorder


def _get_compression_recorder(state: AgentState) -> CompressionMetricsRecorder | None:
    config: dict[str, Any] = cast(dict[str, Any], state.get("_config") or {})
    return cast(
        CompressionMetricsRecorder | None,
        config.get("compression_recorder") or _DEFAULT_COMPRESSION_RECORDER,
    )


def _get_request_id(state: AgentState) -> uuid.UUID:
    raw = state.get("request_id")
    if isinstance(raw, uuid.UUID):
        return raw
    if isinstance(raw, str):
        return uuid.UUID(raw)
    return uuid.uuid4()
