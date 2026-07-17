"""Prometheus metrics and LangGraph node for LLM cost tracking (TASK-US037-03).

Exposes two metric families consumed by Grafana panels (AC-3):
  - contextiq_llm_cost_usd_total   (Counter) — "daily cost by model" panel
  - contextiq_llm_tokens_total     (Counter) — "token budget utilisation" panel

All metrics carry service, model_id, team_id, tenant_id, and intent_type labels
so the Grafana AC-6 filters work correctly.

``llm_metrics_node`` is a LangGraph node positioned immediately after the model
response node and before trace_writer_node.  It increments Prometheus counters
synchronously (no IO) and dispatches the Langfuse write as a fire-and-forget
asyncio task (AC-4) so it adds no latency to the main request path.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from prometheus_client import Counter

from src.agents.state import AgentState
from src.observability.cost.recorder import LLMCostRecorder
from src.observability.cost.schemas import LLMCallRecord

logger = logging.getLogger(__name__)

_COST_LABEL_NAMES = ["service", "model_id", "team_id", "tenant_id", "intent_type"]
_TOKEN_LABEL_NAMES = _COST_LABEL_NAMES + ["token_type"]  # token_type: "prompt"|"completion"

_SERVICE = "contextiq-api"

# AC-1 / AC-3: LLM cost counter — drives "daily cost by model" Grafana panel
contextiq_llm_cost_usd_total = Counter(
    "contextiq_llm_cost_usd_total",
    "Cumulative LLM spend in USD, labelled by model and team.",
    _COST_LABEL_NAMES,
)

# AC-1 / AC-3: Token counter — drives "token budget utilisation" Grafana panel
contextiq_llm_tokens_total = Counter(
    "contextiq_llm_tokens_total",
    "Cumulative LLM tokens consumed, split by prompt and completion.",
    _TOKEN_LABEL_NAMES,
)


async def llm_metrics_node(state: AgentState) -> AgentState:
    """LangGraph node — LLM Cost Metrics.

    Position: immediately after the model response (routing_agent) node,
    before trace_writer_node.

    Steps:
    1. Build LLMCallRecord from AgentState (prompt_tokens, completion_tokens,
       model_selected, cost_usd computed via LiteLLM cost map).
    2. Increment Prometheus cost + token counters synchronously (AC-1, AC-3).
    3. Dispatch LLMCostRecorder.record_llm_call() as asyncio.create_task() (AC-4).
    """
    model_id: str = state.get("model_selected") or state.get("selected_model") or "unknown"
    prompt_tokens: int = state.get("prompt_tokens") or 0
    completion_tokens: int = state.get("completion_tokens") or 0
    jwt_claims: dict = state.get("jwt_claims") or {}
    user_id: str = jwt_claims.get("sub") or "anonymous"
    team_id: str = (
        state.get("team_id")
        or jwt_claims.get("team_id")
        or jwt_claims.get("groups", ["default"])[0]
    )
    tenant_id: str = state.get("tenant_id") or "default"
    intent: str = state.get("intent_type") or state.get("intent") or "unknown"
    # Normalise intent to string (IntentType enum or plain str)
    if hasattr(intent, "value"):
        intent = intent.value

    cost_usd = _compute_cost(model_id, prompt_tokens, completion_tokens)

    # Step 2: Prometheus increments (synchronous — no IO)
    cost_labels = {
        "service": _SERVICE,
        "model_id": model_id,
        "team_id": team_id,
        "tenant_id": tenant_id,
        "intent_type": str(intent),
    }
    contextiq_llm_cost_usd_total.labels(**cost_labels).inc(cost_usd)
    contextiq_llm_tokens_total.labels(**cost_labels, token_type="prompt").inc(prompt_tokens)  # noqa: S106
    contextiq_llm_tokens_total.labels(**cost_labels, token_type="completion").inc(completion_tokens)  # noqa: S106

    # Step 3: Langfuse write — fire-and-forget (AC-4, no latency impact)
    record = LLMCallRecord(
        request_id=_get_request_id(state),
        tenant_id=tenant_id,
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        user_id=user_id,
        team_id=team_id,
        intent_type=str(intent),
        timestamp=datetime.now(tz=UTC),
    )
    recorder: LLMCostRecorder | None = _get_recorder(state)
    if recorder is not None:
        asyncio.create_task(
            _write_langfuse(recorder, record),
            name=f"llm_cost_{record.request_id}",
        )

    return {
        **state,
        "llm_cost_usd": cost_usd,  # expose in state for trace_writer_node
    }


async def _write_langfuse(recorder: LLMCostRecorder, record: LLMCallRecord) -> None:
    """Background coroutine — never raises."""
    try:
        recorder.record_llm_call(record)
    except Exception:
        logger.exception(
            "llm_metrics_node._write_langfuse failed request_id=%s", record.request_id
        )


def _compute_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Use LiteLLM's cost-per-token map to derive cost in USD.

    Falls back to 0.0 if the model is not in the cost map or if litellm is
    unavailable, ensuring the node never raises (AC-1).
    """
    try:
        import litellm  # noqa: PLC0415

        cost = litellm.completion_cost(
            model=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return round(float(cost), 8)
    except Exception:
        logger.debug("litellm.completion_cost unavailable for model=%s", model_id)
        return 0.0


def _get_request_id(state: AgentState) -> UUID:
    import uuid  # noqa: PLC0415

    raw = state.get("request_id")
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str):
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


# ── Injectable singleton ──────────────────────────────────────────────────

_DEFAULT_RECORDER: LLMCostRecorder | None = None


def set_llm_cost_recorder(recorder: LLMCostRecorder) -> None:
    """Register the global LLMCostRecorder used when no per-request recorder is wired."""
    global _DEFAULT_RECORDER  # noqa: PLW0603
    _DEFAULT_RECORDER = recorder


def _get_recorder(state: AgentState) -> LLMCostRecorder | None:
    config: dict = state.get("_config") or {}
    return config.get("llm_cost_recorder") or _DEFAULT_RECORDER
