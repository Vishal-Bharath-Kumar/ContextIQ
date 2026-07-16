"""Stub governance node — implemented in EP-010."""

from src.agents.state import AgentState, ExecutionStatus


async def governance_node(state: AgentState) -> AgentState:
    return {**state, "current_node": "governance_agent", "status": ExecutionStatus.RUNNING}
