from __future__ import annotations

from typing import Any, cast

from src.agents.state import AgentState, ExecutionStatus
from src.model_invoker.schemas.fallback_chain import FallbackChain, InvocationFailure
from src.model_registry.schemas.model_definition import LatencyTier
from src.model_router.runtime_services import RoutingRuntimeServices
from src.observability.tracing.node_span import otel_node_span

_SYSTEM_PROMPT = (
    "You are ContextIQ, an enterprise engineering assistant. "
    "Answer the user's prompt using the supplied context. "
    "Be precise, say when the provided context is insufficient, and cite "
    "relevant file paths or source identifiers when useful."
)


@otel_node_span("routing.llm_response")
async def llm_response_node(state: AgentState) -> AgentState:
    config = cast(dict[str, Any], state.get("_config") or {})
    runtime_services = cast(RoutingRuntimeServices | None, config.get("routing_runtime"))
    selected_model = str(state.get("selected_model") or "")
    fallback_chain_ids = [
        model_id for model_id in (state.get("fallback_chain") or [selected_model]) if model_id
    ]
    base_response = dict(state.get("final_response") or {})

    if str(state.get("tool_name") or "") == "generate_context":
        return {
            "final_response": base_response,
            "current_node": "llm_response_agent",
            "status": ExecutionStatus.COMPLETE,
        }

    if runtime_services is None or not selected_model or not fallback_chain_ids:
        return {
            "final_response": base_response,
            "current_node": "llm_response_agent",
            "status": ExecutionStatus.COMPLETE,
        }

    chain = FallbackChain(
        model_ids=fallback_chain_ids,
        intent_type=str(state.get("intent_type") or "general"),
    )
    try:
        latency_tier = await _resolve_latency_tier(runtime_services, selected_model)
        invocation = await runtime_services.fallback_invoker.invoke(
            fallback_chain=chain,
            messages=_build_messages(state),
            token_budget=_response_token_budget(state),
            latency_tier=latency_tier,
        )
    except Exception as exc:
        degraded = list(base_response.get("degraded_sources") or [])
        degraded.append(
            {
                "source_id": "llm-response",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        base_response["degraded_sources"] = degraded
        base_response["invocation_error"] = str(exc)
        return {
            "final_response": base_response,
            "current_node": "llm_response_agent",
            "status": ExecutionStatus.COMPLETE,
        }

    if isinstance(invocation, InvocationFailure):
        degraded = list(base_response.get("degraded_sources") or [])
        degraded.append(
            {
                "source_id": "llm-response",
                "error_type": "InvocationFailure",
                "message": invocation.message,
            }
        )
        base_response["degraded_sources"] = degraded
        base_response["invocation_error"] = invocation.message
        return {
            "final_response": base_response,
            "current_node": "llm_response_agent",
            "status": ExecutionStatus.COMPLETE,
        }

    return {
        "selected_model": invocation.model_id,
        "final_response": {
            **base_response,
            "type": "llm_response",
            "selected_model": invocation.model_id,
            "answer": invocation.content,
            "usage": {
                "input_tokens": invocation.input_tokens,
                "output_tokens": invocation.output_tokens,
                "finish_reason": invocation.finish_reason,
            },
        },
        "current_node": "llm_response_agent",
        "status": ExecutionStatus.COMPLETE,
    }


def _build_messages(state: AgentState) -> list[dict[str, str]]:
    final_response = cast(dict[str, Any], state.get("final_response") or {})
    context_items = final_response.get("context") or []
    context_text = _render_context(context_items)
    governance = cast(dict[str, Any], final_response.get("governance") or {})
    governance_summary = governance.get("summary")

    user_message = (
        f"User prompt:\n{state.get('prompt', '')}\n\n"
        f"Classified intent: {state.get('intent_type') or 'general'}\n"
        f"Intent confidence: {float(state.get('intent_confidence') or 1.0):.2f}\n\n"
        f"Governance summary:\n{governance_summary or 'No additional governance notes.'}\n\n"
        f"Retrieved context:\n{context_text}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def _render_context(items: list[object]) -> str:
    if not items:
        return "No retrieved context was available."

    rendered: list[str] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, dict):
            source_id = item.get("source_id") or item.get("source") or "unknown"
            location = item.get("path") or item.get("document_id") or item.get("chunk_id") or f"item-{idx}"
            content = item.get("content") or item.get("text") or item.get("summary") or item.get("value") or ""
            rendered.append(f"[{idx}] source={source_id} location={location}\n{content}".strip())
        else:
            rendered.append(f"[{idx}] {item}")
    return "\n\n".join(rendered)


async def _resolve_latency_tier(
    runtime_services: RoutingRuntimeServices,
    selected_model: str,
) -> LatencyTier:
    model = await runtime_services.get_model_definition(selected_model)
    if model is None:
        return LatencyTier.MEDIUM
    return model.latency_tier


def _response_token_budget(state: AgentState) -> int:
    execution_plan = state.get("execution_plan")
    if isinstance(execution_plan, dict):
        total_budget = int(execution_plan.get("token_budget_total") or 4_000)
    elif execution_plan is not None:
        total_budget = int(execution_plan.token_budget_total)
    else:
        total_budget = 4_000
    return min(2_048, max(512, total_budget // 4))