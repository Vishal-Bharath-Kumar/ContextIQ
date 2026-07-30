"""FastAPI router for ``POST /v1/execute`` and ``GET /healthz``.

TASK-US005-02: Implement ``POST /v1/execute`` Entrypoint and Initial State Hydration.

Responsibilities
----------------
* Receive an :class:`~src.agent_worker.schemas.execute_types.ExecuteRequest` from
  the MCP Gateway.
* Construct the initial :class:`~src.agents.state.AgentState` and set
  ``status = ExecutionStatus.PENDING`` before graph invocation.
* Invoke the compiled LangGraph graph via ``graph.ainvoke``.
* Return a structured :class:`~src.agent_worker.schemas.execute_types.ExecuteResponse`
  for both success and error paths — the gateway always receives HTTP 200 with a
  typed payload.
* ``GET /healthz`` confirms the graph is compiled and the service is ready.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from langgraph.graph.state import CompiledStateGraph

from src.agent_worker.schemas.execute_types import ExecuteRequest, ExecuteResponse, ToolCallError
from src.agents.state import AgentState, ExecutionStatus
from src.governance.opa.health import default_opa_health_status
from src.llm.ollama_verify import default_ollama_verification_status

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Dependency provider — overridden in tests via app.dependency_overrides
# ---------------------------------------------------------------------------

_compiled_graph: CompiledStateGraph | None = None


def set_graph(graph: CompiledStateGraph) -> None:
    """Store the compiled graph used by :func:`get_graph`.

    Call this once during application startup (e.g. from the lifespan).
    """
    global _compiled_graph  # noqa: PLW0603
    _compiled_graph = graph


def get_graph() -> CompiledStateGraph:
    """FastAPI dependency that returns the module-level compiled graph.

    Raises
    ------
    RuntimeError
        If :func:`set_graph` has not been called before the first request.
    """
    if _compiled_graph is None:
        raise RuntimeError("Graph not initialised — call set_graph() during startup.")
    return _compiled_graph


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/healthz", summary="Health check")
async def healthz(request: Request) -> dict:
    """Return service health including whether the graph is compiled."""
    return {
        "status": "ok",
        "graph_compiled": _compiled_graph is not None,
        "ollama": getattr(request.app.state, "ollama_verification", default_ollama_verification_status()),
        "opa": getattr(request.app.state, "opa_health", default_opa_health_status()),
    }


@router.post(
    "/v1/execute",
    response_model=ExecuteResponse,
    summary="Execute a tool via the LangGraph pipeline",
)
async def execute(
    req: ExecuteRequest,
    graph: CompiledStateGraph = Depends(get_graph),
) -> ExecuteResponse:
    """Hydrate the initial :class:`AgentState` and invoke the compiled graph.

    The endpoint always returns HTTP 200.  Pipeline failures are captured and
    returned as a structured ``ExecuteResponse`` with ``status = "error"`` so
    the MCP Gateway always receives a typed payload.
    """
    initial_state: AgentState = {
        "request_id": req.request_id,
        "user_id": req.user_id,
        "username": req.username,
        "roles": req.roles,
        "tool_name": req.tool_name,
        "prompt": req.arguments.get("prompt", ""),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": ExecutionStatus.PENDING,
        "current_node": "",
        "error": None,
        # All downstream fields initialised to None — set by pipeline nodes.
        "intent_type": None,
        "intent_confidence": None,
        "execution_plan": None,
        "raw_context": None,
        "ranked_context": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
        "degraded_sources": None,
    }
    if req.jwt_claims is not None:
        initial_state["jwt_claims"] = req.jwt_claims
    if req.tenant_id is not None:
        initial_state["tenant_id"] = req.tenant_id

    config = {"configurable": {"thread_id": req.request_id}}
    t_start = time.monotonic()

    try:
        final_state = await graph.ainvoke(initial_state, config=config)
        duration_ms = int((time.monotonic() - t_start) * 1000)

        if final_state.get("status") == ExecutionStatus.FAILED:
            error_detail: dict = json.loads(final_state.get("error") or "{}")
            logger.warning(
                "pipeline.failed tool=%s request_id=%s failed_node=%s duration_ms=%d",
                req.tool_name,
                req.request_id,
                error_detail.get("failed_node", "unknown"),
                duration_ms,
            )
            return ExecuteResponse(
                request_id=req.request_id,
                status="error",
                error=ToolCallError(
                    code=-32603,
                    message=error_detail.get("message", "Pipeline failed"),
                    data=error_detail,
                ),
                duration_ms=duration_ms,
            )

        logger.info(
            "pipeline.success tool=%s request_id=%s duration_ms=%d",
            req.tool_name,
            req.request_id,
            duration_ms,
        )
        degraded = final_state.get("degraded_sources") or []
        output_payload: dict = {
            **(final_state.get("final_response") or {}),
            "degraded_sources": degraded,
        }
        return ExecuteResponse(
            request_id=req.request_id,
            status="success",
            output=output_payload,
            duration_ms=duration_ms,
        )
    except Exception:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        logger.exception(
            "pipeline.failure tool=%s request_id=%s", req.tool_name, req.request_id
        )
        return ExecuteResponse(
            request_id=req.request_id,
            status="error",
            error=ToolCallError(code=-32603, message="Internal pipeline error"),
            duration_ms=duration_ms,
        )
