"""Stub compression node — implemented in EP-005."""

from src.agents.state import AgentState, ExecutionStatus


async def compression_node(state: AgentState) -> AgentState:
    return {**state, "current_node": "compression_agent", "status": ExecutionStatus.RUNNING}
