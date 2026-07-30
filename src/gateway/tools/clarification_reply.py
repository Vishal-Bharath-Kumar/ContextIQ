"""``clarification_reply`` MCP tool — TASK-US011-04.

Accepts the user's answer to the clarification question, merges it with the
original prompt into a single enriched prompt, and re-enters the LangGraph
pipeline from the ``intent_agent`` node with ``clarification_round = 1``.

The compiled graph must be injected at gateway startup via ``set_graph()``
before any request reaches this tool.  The pattern mirrors the agent worker's
``src.agent_worker.routers.execute.set_graph`` contract.
"""
from __future__ import annotations

import json
import logging

from fastmcp import FastMCP
from langgraph.graph.state import CompiledStateGraph
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS, ErrorData, TextContent

from src.agents.planning.prompt_merger import merge_prompt
from src.agents.state import ExecutionStatus
from src.gateway.schemas.clarification_reply import ClarificationReplyInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level graph singleton — set at gateway startup via set_graph().
# ---------------------------------------------------------------------------

_graph: CompiledStateGraph | None = None


def set_graph(graph: CompiledStateGraph) -> None:
    """Store the compiled graph used by ``clarification_reply``.

    Call once during gateway startup after building the graph with a Redis
    checkpointer.
    """
    global _graph  # noqa: PLW0603
    _graph = graph


def _get_graph() -> CompiledStateGraph:
    if _graph is None:
        raise RuntimeError(
            "clarification_reply: graph not initialised — call set_graph() at startup."
        )
    return _graph


def get_graph() -> CompiledStateGraph:
    """Public accessor for the gateway-compiled graph."""
    return _get_graph()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_clarification_reply_tool(mcp: FastMCP) -> None:
    """Register the ``clarification_reply`` tool on *mcp*.

    Parameters
    ----------
    mcp:
        The FastMCP server instance.
    """

    @mcp.tool()
    async def clarification_reply(session_id: str, clarification: str) -> list[TextContent]:
        """Submit a clarification answer and resume the pipeline with the enriched prompt."""
        args = ClarificationReplyInput(session_id=session_id, clarification=clarification)

        graph = _get_graph()

        # Restore previous AgentState from LangGraph checkpointer via thread_id.
        prior_state = await graph.aget_state(
            config={"configurable": {"thread_id": args.session_id}}
        )
        if prior_state is None:
            raise McpError(
                ErrorData(
                    code=INVALID_PARAMS,
                    message=f"Session '{args.session_id}' not found or expired",
                )
            )

        values = prior_state.values
        merged = merge_prompt(
            original_prompt=values["prompt"],
            clarification_question=values["clarification_question"],
            user_clarification=args.clarification,
        )

        # Build re-entry state patch — reset intent fields for a fresh second-pass.
        resume_state: dict = {
            "prompt": merged,
            "clarification_round": 1,
            "requires_clarification": False,
            "status": ExecutionStatus.PENDING,
            "intent_type": None,
            "intent_confidence": None,
            "intent_source_list": None,
            "execution_plan": None,
        }

        result = await graph.ainvoke(
            resume_state,
            config={"configurable": {"thread_id": args.session_id}},
        )

        return [TextContent(type="text", text=json.dumps(result.get("final_response", {})))]
