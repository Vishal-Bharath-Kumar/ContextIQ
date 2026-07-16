"""LangGraph StateGraph definition for the ContextIQ multi-agent pipeline.

This module is the **single source of truth** for pipeline topology.
No topology logic (edges, routing decisions) belongs in node files.

Topology overview::

                      [intent_agent]
                           │
          ┌────────────────┴────────────────┐
    confidence < 0.6                  confidence ≥ 0.6
          │                                  │
 [clarification_response]           [retrieval_agent]
          │                                  │
         END                        [governance_agent]
                                             │
                                ┌────────────┴────────────┐
                           tokens ≤ budget           tokens > budget
                                │                         │
                           [routing_agent]      [compression_agent]
                                │                         │
                               END                 [routing_agent]
                                                         │
                                                        END

Any node that sets ``status = FAILED`` is routed to ``[pipeline_failed] → END``.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.events.state_event_publisher import StateEventPublisher, with_state_events
from src.agents.nodes.base import NodeWrapper
from src.agents.nodes.clarification_node import clarification_node
from src.agents.nodes.compression import compression_node
from src.agents.nodes.governance import governance_node
from src.agents.nodes.intent import intent_node
from src.agents.nodes.pipeline_failed import failed_terminal_node  # re-exported for back-compat
from src.agents.nodes.retrieval import retrieval_node
from src.agents.nodes.routing import routing_node
from src.agents.routing import route_after_governance, route_after_intent
from src.agents.state import AgentState


def build_graph(
    checkpointer: object = None,
    publisher: StateEventPublisher | None = None,
) -> CompiledStateGraph:
    """Build and compile the ContextIQ LangGraph StateGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer (e.g. Redis-backed).
                      Wired in TASK-US005-03; defaults to ``None`` for tests.
        publisher: Optional ``StateEventPublisher`` for Kafka state-transition
                   events (TASK-US005-04).  When provided every node is wrapped
                   with ``with_state_events``; omitting it disables event
                   publishing (e.g. in unit tests).

    Returns:
        A compiled LangGraph graph ready for invocation.
    """

    def _wrap(fn: object, name: str, *, is_final: bool = False) -> object:
        """Apply the full wrapper stack (error handling, contract, logging, events)."""
        return NodeWrapper.wrap(fn, name, publisher=publisher, is_final=is_final)

    def _wrap_terminal(fn: object, name: str) -> object:
        """Wrap terminal nodes with state-events only (no contract enforcement)."""
        if publisher is None:
            return fn
        return with_state_events(fn, name, publisher, is_final=True)

    builder: StateGraph = StateGraph(AgentState)

    # ── Register all seven nodes ──────────────────────────────────────────
    builder.add_node("intent_agent", _wrap(intent_node, "intent_agent"))
    builder.add_node("retrieval_agent", _wrap(retrieval_node, "retrieval_agent"))
    builder.add_node("governance_agent", _wrap(governance_node, "governance_agent"))
    builder.add_node("compression_agent", _wrap(compression_node, "compression_agent"))
    builder.add_node("routing_agent", _wrap(routing_node, "routing_agent", is_final=True))
    builder.add_node("clarification_response", _wrap_terminal(clarification_node, "clarification_response"))
    builder.add_node("pipeline_failed", _wrap_terminal(failed_terminal_node, "pipeline_failed"))

    # ── Entry point ────────────────────────────────────────────────────
    builder.set_entry_point("intent_agent")

    # ── Intent → conditional branch (clarification / retrieval / failed) ──
    builder.add_conditional_edges(
        "intent_agent",
        route_after_intent,
        {
            "retrieval": "retrieval_agent",
            "clarification": "clarification_response",
            "failed": "pipeline_failed",
        },
    )

    # ── Retrieval → Governance (always) ───────────────────────────────
    builder.add_edge("retrieval_agent", "governance_agent")

    # ── Governance → conditional compression branch ────────────────────
    builder.add_conditional_edges(
        "governance_agent",
        route_after_governance,
        {
            "compress": "compression_agent",
            "skip": "routing_agent",
            "failed": "pipeline_failed",
        },
    )

    # ── Compression → Routing (always, after compression) ─────────────
    builder.add_edge("compression_agent", "routing_agent")

    # ── Terminal edges ─────────────────────────────────────────────────
    builder.add_edge("routing_agent", END)
    builder.add_edge("clarification_response", END)
    builder.add_edge("pipeline_failed", END)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
