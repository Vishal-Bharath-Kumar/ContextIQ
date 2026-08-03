"""Routing adapter for the active LangGraph pipeline.

This node emits a usable final response even when the Redis-backed model-routing
dependencies are not wired into the graph runtime.
"""

from __future__ import annotations

from typing import Any, cast

from src.agents.state import AgentState, ExecutionStatus
from src.agents.nodes.routing_node import routing_node as select_model_node
from src.model_router.config import RoutingSettings
from src.model_router.runtime_services import RoutingRuntimeServices
from src.observability.tracing.node_span import otel_node_span

_settings = RoutingSettings()


@otel_node_span("routing.model_select")
async def routing_node(state: AgentState) -> AgentState:
    config = cast(dict[str, Any], state.get("_config") or {})
    selected_model = _settings.fallback_model_id
    routing_score = 0.0
    fallback_chain = [selected_model]
    degraded_sources = list(state.get("degraded_sources") or [])

    runtime_services = cast(RoutingRuntimeServices | None, config.get("routing_runtime"))
    model_list_cache = getattr(runtime_services, "model_list_cache", None) or config.get("model_list_cache")
    scored_cache = getattr(runtime_services, "scored_model_cache", None) or config.get("scored_model_cache")
    langfuse = getattr(runtime_services, "langfuse", None) or config.get("langfuse")

    if model_list_cache is not None and scored_cache is not None:
        try:
            routing_result = await select_model_node(
                state,
                model_list_cache=model_list_cache,
                scored_cache=scored_cache,
                langfuse=langfuse,
            )
            selected_model = str(routing_result.get("selected_model_id") or selected_model)
            routing_score = float(routing_result.get("routing_score") or 0.0)
            fallback_chain = list(routing_result.get("fallback_chain") or [selected_model])
        except Exception as exc:
            degraded_sources.append(
                {
                    "source_id": "model-routing",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    active_context = state.get("compressed_context") or state.get("ranked_context") or []

    return {
        "selected_model": selected_model,
        "model_routing_score": routing_score,
        "fallback_chain": fallback_chain,
        "final_response": {
            "type": "context_package",
            "prompt": state.get("prompt", ""),
            "intent": str(state.get("intent_type") or "general"),
            "selected_model": selected_model,
            "model_routing_score": routing_score,
            "fallback_chain": fallback_chain,
            "context": [_serialise_context_item(item) for item in active_context],
            "governance": {
                "blocked": bool(state.get("governance_blocked", False)),
                "redacted": bool(state.get("context_redacted", False)),
                "findings_count": len(state.get("governance_findings") or []),
                "summary": state.get("governance_summary"),
            },
            "degraded_sources": degraded_sources,
        },
        "current_node": "routing_agent",
        "status": ExecutionStatus.RUNNING,
    }


def _serialise_context_item(item: object) -> dict[str, object]:
    if hasattr(item, "model_dump"):
        return cast(dict[str, object], item.model_dump())
    if isinstance(item, dict):
        return item
    return {"value": str(item)}
