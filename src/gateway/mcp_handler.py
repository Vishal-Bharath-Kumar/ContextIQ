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
        tool_input=_merge_request_identity(request, body),
        connector_registry=getattr(request.app.state, "connector_registry", None),
        runtime_config=_runtime_config_from_request(request),
    )
    return _serialise_context_query_result(result)


async def handle_tool_call(
    request_id: uuid.UUID,
    tool_input: dict[str, Any],
    connector_registry: object | None = None,
    runtime_config: dict[str, object] | None = None,
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
        pipeline = build_pipeline(runtime_config=runtime_config)
        state = _build_initial_state(request_id, tool_input)
        state["_otel_ctx"] = rsc
        state["otel_trace_id"] = rsc.trace_id_hex
        config = {"configurable": {"thread_id": str(request_id)}}
        return await pipeline.ainvoke(state, config=config)


def _build_initial_state(request_id: uuid.UUID, tool_input: dict[str, Any]) -> dict[str, Any]:
    state = {
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
    if tool_input.get("jwt_claims") is not None:
        state["jwt_claims"] = tool_input["jwt_claims"]
    if tool_input.get("tenant_id") is not None:
        state["tenant_id"] = str(tool_input["tenant_id"])
    return state


def _merge_request_identity(request: Request, tool_input: dict[str, Any]) -> dict[str, Any]:
    merged = dict(tool_input)
    claims = getattr(request.state, "jwt_claims", None)
    if claims is None:
        return merged

    merged.setdefault("user_id", claims.sub)
    merged.setdefault("username", claims.preferred_username or "")
    merged.setdefault("roles", list(claims.roles))
    merged.setdefault("jwt_claims", claims.model_dump(mode="python"))

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is not None:
        merged.setdefault("tenant_id", tenant_id)
    return merged


def _runtime_config_from_request(request: Request) -> dict[str, object] | None:
    routing_runtime = getattr(request.app.state, "routing_runtime", None)
    if routing_runtime is None:
        return None
    return {"routing_runtime": routing_runtime}


def _serialise_context_query_result(result: dict[str, Any]) -> dict[str, Any]:
    final_response = result.get("final_response")
    if isinstance(final_response, dict):
        return final_response

    return {
        "type": "pipeline_error",
        "status": str(result.get("status") or "failed"),
        "request_id": str(result.get("request_id") or ""),
        "current_node": str(result.get("current_node") or "unknown"),
        "error": result.get("error"),
        "selected_model": result.get("selected_model"),
        "model_routing_score": result.get("model_routing_score"),
        "degraded_sources": result.get("degraded_sources") or [],
    }
