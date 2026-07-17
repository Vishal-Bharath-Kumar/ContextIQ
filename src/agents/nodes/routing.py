"""Stub model routing node — implemented in EP-006."""

from src.agents.state import AgentState, ExecutionStatus
from src.observability.tracing.node_span import otel_node_span


@otel_node_span("routing.model_select")
async def routing_node(state: AgentState) -> AgentState:
    return {**state, "current_node": "routing_agent", "status": ExecutionStatus.COMPLETE}
