"""Stub model routing node — implemented in EP-006."""

from src.agents.state import AgentState, ExecutionStatus


async def routing_node(state: AgentState) -> AgentState:
    return {**state, "current_node": "routing_agent", "status": ExecutionStatus.COMPLETE}
