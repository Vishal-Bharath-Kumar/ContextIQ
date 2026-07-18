"""routing_node() — LangGraph node for dynamic model selection (TASK-US019-04).

Reads ``intent_type`` from ``AgentState.execution_plan``, delegates to
``ModelRouter.select()``, and writes ``selected_model_id`` and
``routing_score`` back to state.  Emits an OTel span and optionally a
Langfuse event capturing the routing decision.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from opentelemetry import trace

from src.agents.state import AgentState
from src.model_registry.cache.model_cache import ModelListCache
from src.model_router.cache.scored_model_cache import ScoredModelCache
from src.model_router.config import RoutingSettings
from src.model_router.router import ModelRouter

if TYPE_CHECKING:
    from langfuse import Langfuse

_tracer = trace.get_tracer(__name__)
_settings = RoutingSettings()

# Module-level singleton — initialised once at import time
_FALLBACK_MODEL_ID: str = _settings.fallback_model_id


async def routing_node(
    state: AgentState,
    model_list_cache: ModelListCache,  # injected via functools.partial at graph build
    scored_cache: ScoredModelCache,  # injected via functools.partial at graph build
    langfuse: Langfuse | None,  # None when Langfuse disabled in env
) -> AgentState:
    """Select the best model for the current intent and annotate state.

    Args:
        state:            Current ``AgentState``.
        model_list_cache: Active model list cache (Redis-backed).
        scored_cache:     Pre-scored model candidate cache (Redis-backed).
        langfuse:         Langfuse client for event emission; ``None`` disables it.

    Returns:
        Updated ``AgentState`` with ``selected_model_id`` and ``routing_score`` set.
    """
    with _tracer.start_as_current_span("model_router.select") as span:
        t0 = time.perf_counter()
        raw_intent = state.get("intent_type")  # type: ignore[typeddict-item]
        intent_type: str = str(raw_intent) if raw_intent is not None else "general"

        router = ModelRouter(
            model_list_cache=model_list_cache,
            scored_model_cache=scored_cache,
        )

        selection = await router.select(intent_type=intent_type)

        if selection is None:
            selected_model_id = _FALLBACK_MODEL_ID
            routing_score = 0.0
            routing_reason = f"No eligible model found; defaulted to {_FALLBACK_MODEL_ID}"
        else:
            selected_model_id = selection.model_id
            routing_score = selection.composite_score
            routing_reason = (
                f"Selected '{selection.model_id}' for intent '{intent_type}' "
                f"(composite_score={selection.composite_score:.4f}, "
                f"quality={selection.quality_score:.2f}, "
                f"normalised_cost={selection.normalised_cost:.4f})"
            )

        fallback = await router.build_fallback_chain(intent_type=intent_type)
        fallback_chain_ids = fallback.model_ids if fallback is not None else [selected_model_id]

        latency_ms = (time.perf_counter() - t0) * 1000

        # OTel span attributes
        span.set_attribute("routing.model_id", selected_model_id)
        span.set_attribute("routing.score", routing_score)
        span.set_attribute("routing.intent", intent_type)
        span.set_attribute("routing.latency_ms", round(latency_ms, 2))
        span.set_attribute("routing.fallback", selection is None)

        # Langfuse event — skipped entirely when langfuse is None
        if langfuse is not None:
            langfuse.event(
                name="model_routing_decision",
                input={"intent_type": intent_type},
                output={"model_id": selected_model_id, "score": routing_score},
                metadata={
                    "routing_reason": routing_reason,
                    "latency_ms": latency_ms,
                    "used_fallback": selection is None,
                },
                session_id=state.get("session_id"),  # type: ignore[typeddict-item]
            )

    return {
        **state,
        "selected_model_id": selected_model_id,
        "routing_score": routing_score,
        "fallback_chain": fallback_chain_ids,
    }
