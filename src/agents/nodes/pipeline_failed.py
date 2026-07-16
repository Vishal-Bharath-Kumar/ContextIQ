"""pipeline_failed — terminal node for the ContextIQ failure path.

This module provides the ``failed_terminal_node`` coroutine which is registered
as the ``pipeline_failed`` node in the compiled ``StateGraph``.  It is a no-op
terminal: the state already carries ``status=FAILED`` and a structured ``error``
payload set by ``with_error_handling`` on the node that raised.  This node's
sole purpose is to be an explicit named endpoint visible in pipeline topology
diagrams and LangGraph trace output.
"""
from __future__ import annotations

from src.agents.state import AgentState, ExecutionStatus


async def failed_terminal_node(state: AgentState) -> dict:
    """Terminal node reached when any upstream pipeline node raises an exception.

    The ``error`` and ``status=FAILED`` fields are already present in *state*,
    set by the ``with_error_handling`` wrapper on the failing node.  This node
    only canonicalises ``current_node`` so the final state is unambiguous.

    Args:
        state: Current ``AgentState`` — expected to already have
               ``status=FAILED`` and ``error`` populated.

    Returns:
        Partial state update with ``status=FAILED`` and
        ``current_node="pipeline_failed"``.
    """
    return {
        "status": ExecutionStatus.FAILED,
        "current_node": "pipeline_failed",
    }
