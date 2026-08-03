"""Calibrated stub nodes for end-to-end pipeline SLA benchmarks.

Each stub node simulates its realistic median latency using ``asyncio.sleep``
so that benchmark runs measure graph overhead + sub-agent durations without
requiring live infrastructure.

Latency budget per node (TASK-US006-05 design estimates):

  Node                  Median    p95     Stub sleep
  ────────────────────  ──────    ────    ──────────
  intent_agent          200 ms    400 ms  200 ms
  retrieval_agent       800 ms  1 200 ms  800 ms
  governance_agent      100 ms    200 ms  100 ms
  compression_agent     200 ms    400 ms  200 ms (full path only)
  routing_agent          50 ms    100 ms   50 ms
  ────────────────────  ──────    ────    ──────────
  Total (full path)   1 350 ms  2 300 ms  < 3 000 ms ✓
  Total (skip comp.)  1 150 ms  1 900 ms  < 2 000 ms ✓
"""
from __future__ import annotations

import asyncio

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.routing import route_after_governance, route_after_intent
from src.agents.state import AgentState, ExecutionStatus

# ---------------------------------------------------------------------------
# Stub node definitions
# ---------------------------------------------------------------------------

# Token counts that force the governance→compression branch (full path).
# 20 chunks × 500 tokens = 10 000 > 8 000 default budget.
_FULL_PATH_TOKEN_COUNT = 500

# Token counts that force the governance→skip branch (skip compression path).
# 20 chunks × 80 tokens = 1 600 ≤ 8 000 default budget.
_SKIP_PATH_TOKEN_COUNT = 80


async def stub_intent_node(state: AgentState) -> dict:
    """200 ms stub — simulates intent classification."""
    await asyncio.sleep(0.200)
    return {
        "intent_type": "debugging",
        "intent_confidence": 0.85,
        "execution_plan": {
            "token_budget_total": 8000,
            "sources": ["github", "confluence"],
        },
        "status": ExecutionStatus.RUNNING,
        "current_node": "intent_agent",
    }


def _make_stub_retrieval_node(token_count_per_chunk: int):
    """Return a retrieval stub that produces chunks with the given token count."""

    async def stub_retrieval_node(state: AgentState) -> dict:
        """800 ms stub — simulates vector + graph retrieval."""
        await asyncio.sleep(0.800)
        chunks = [
            {"id": f"c{i}", "content": "x" * 100, "token_count": token_count_per_chunk}
            for i in range(20)
        ]
        return {
            "raw_context": chunks,
            "ranked_context": chunks,
            "current_node": "retrieval_agent",
        }

    return stub_retrieval_node


async def stub_governance_node(state: AgentState) -> dict:
    """100 ms stub — simulates access-control governance checks."""
    await asyncio.sleep(0.100)
    return {
        "governance_decisions": [{"chunk_id": f"c{i}", "allowed": True} for i in range(20)],
        "redacted_chunks": [],
        "current_node": "governance_agent",
    }


async def stub_compression_node(state: AgentState) -> dict:
    """200 ms stub — simulates token-budget compression."""
    await asyncio.sleep(0.200)
    ranked = state.get("ranked_context") or []
    budget: int = (state.get("execution_plan") or {}).get("token_budget_total", 8000)
    compressed = ranked[: len(ranked) // 2]  # naive halve
    return {
        "compressed_context": compressed,
        "tokens_before_compression": sum(c.get("token_count", 0) for c in ranked),
        "tokens_after_compression": budget - 100,
        "current_node": "compression_agent",
    }


async def stub_routing_node(state: AgentState) -> dict:
    """50 ms stub — simulates model selection and final-response assembly."""
    await asyncio.sleep(0.050)
    return {
        "selected_model": "gpt-4o",
        "model_routing_score": 0.92,
        "final_response": {
            "type": "answer",
            "message": "Service X is slow because of N+1 queries.",
        },
        "status": ExecutionStatus.COMPLETE,
        "current_node": "routing_agent",
    }


async def stub_clarification_node(state: AgentState) -> dict:
    """Terminal stub — clarification response (no sleep; rarely reached in benchmarks)."""
    question = (state.get("execution_plan") or {}).get("clarification_question", "")
    return {
        "current_node": "clarification_response",
        "status": ExecutionStatus.COMPLETE,
        "final_response": {"type": "clarification", "message": question},
    }


async def stub_failed_node(state: AgentState) -> dict:
    """Terminal stub — pipeline failure (no sleep)."""
    return {
        "current_node": "pipeline_failed",
        "status": ExecutionStatus.FAILED,
    }


# ---------------------------------------------------------------------------
# Stub graph factory
# ---------------------------------------------------------------------------


def build_stub_graph(compression_skip: bool = False) -> CompiledStateGraph:
    """Build a LangGraph StateGraph wired with latency stubs.

    Args:
        compression_skip: When ``True``, the retrieval stub returns context
            whose total token count fits within the default 8 000-token budget,
            bypassing the ``compression_agent`` node.  When ``False`` (default),
            tokens exceed the budget and the full compression path is exercised.

    Returns:
        A compiled ``CompiledStateGraph`` ready for ``ainvoke``.
    """
    token_per_chunk = _SKIP_PATH_TOKEN_COUNT if compression_skip else _FULL_PATH_TOKEN_COUNT
    retrieval_stub = _make_stub_retrieval_node(token_per_chunk)

    builder: StateGraph = StateGraph(AgentState)

    builder.add_node("intent_agent", stub_intent_node)
    builder.add_node("retrieval_agent", retrieval_stub)
    builder.add_node("governance_agent", stub_governance_node)
    builder.add_node("compression_agent", stub_compression_node)
    builder.add_node("routing_agent", stub_routing_node)
    builder.add_node("clarification_response", stub_clarification_node)
    builder.add_node("pipeline_failed", stub_failed_node)

    builder.set_entry_point("intent_agent")

    builder.add_conditional_edges(
        "intent_agent",
        route_after_intent,
        {
            "retrieval": "retrieval_agent",
            "clarification": "clarification_response",
            "failed": "pipeline_failed",
        },
    )

    builder.add_edge("retrieval_agent", "governance_agent")

    builder.add_conditional_edges(
        "governance_agent",
        route_after_governance,
        {
            "compress": "compression_agent",
            "skip": "routing_agent",
            "failed": "pipeline_failed",
        },
    )

    builder.add_edge("compression_agent", "routing_agent")
    builder.add_edge("routing_agent", END)
    builder.add_edge("clarification_response", END)
    builder.add_edge("pipeline_failed", END)

    return builder.compile()
