import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from src.auth import require_context_tools
from src.observability.tracing.root_span import start_root_span

mcp_router = APIRouter(
    prefix="/tools",
    tags=["MCP Tools"],
    dependencies=[Depends(require_context_tools)],
)


@mcp_router.post("/context_query")
async def context_query(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    result = await handle_tool_call(
        request_id=uuid.uuid4(),
        tool_input=body,
        connector_registry=getattr(request.app.state, "connector_registry", None),
    )
    return result.get("final_response") or result


async def handle_tool_call(
    request_id: uuid.UUID,
    tool_input: dict[str, Any],
    connector_registry: object | None = None,
) -> dict[str, Any]:
    """Invoke the LangGraph pipeline under a root OTel span.

    Creates a root span whose trace ID equals ``request_id`` (AC-1), stores
    :class:`~src.observability.tracing.root_span.RootSpanContext` in the
    pipeline state, then invokes the pipeline.
    """
    from src.agents.graph import build_pipeline  # local import avoids circular deps
    from src.agents.nodes.retrieval import set_connector_registry

    if connector_registry is not None:
        set_connector_registry(connector_registry)

    with start_root_span(request_id, operation="mcp.context_query") as rsc:
        pipeline = build_pipeline()
        state = _build_initial_state(request_id, tool_input)
        state["_otel_ctx"] = rsc
        state["otel_trace_id"] = rsc.trace_id_hex
        return await pipeline.ainvoke(state)


def _build_initial_state(request_id: uuid.UUID, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(request_id),
        "user_id": str(tool_input.get("user_id") or "anonymous"),
        "username": str(tool_input.get("username") or ""),
        "roles": list(tool_input.get("roles") or []),
        "tool_name": str(tool_input.get("tool_name") or "context_query"),
        "prompt": str(tool_input.get("prompt") or tool_input.get("query") or ""),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "pending",
        "current_node": "",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "intent_source_list": None,
        "execution_plan": None,
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
    }
