import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends

from src.auth import require_context_tools
from src.observability.tracing.root_span import start_root_span

mcp_router = APIRouter(
    prefix="/tools",
    tags=["MCP Tools"],
    dependencies=[Depends(require_context_tools)],
)


@mcp_router.post("/context_query")
async def context_query(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return {"result": "stub"}


async def handle_tool_call(request_id: uuid.UUID, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Invoke the LangGraph pipeline under a root OTel span.

    Creates a root span whose trace ID equals ``request_id`` (AC-1), stores
    :class:`~src.observability.tracing.root_span.RootSpanContext` in the
    pipeline state, then invokes the pipeline.
    """
    from src.agents.graph import build_pipeline  # local import avoids circular deps

    with start_root_span(request_id, operation="mcp.context_query") as rsc:
        pipeline = build_pipeline()
        state: dict[str, Any] = {**tool_input}
        state["_otel_ctx"] = rsc
        state["otel_trace_id"] = rsc.trace_id_hex
        return await pipeline.ainvoke(state)
