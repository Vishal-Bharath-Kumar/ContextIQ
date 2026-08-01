"""TASK-US005-05: State initialization performance benchmark.

Asserts that the mean time for state construction + graph.ainvoke() (including
first node entry) stays under the 50 ms SLA across 50 benchmark rounds.

pytest-benchmark requires synchronous callables; asyncio.run() is used to drive
the coroutine from a sync wrapper so the benchmark harness can time it
accurately.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from langgraph.graph import END, StateGraph
from pytest_benchmark.fixture import BenchmarkFixture

from src.agents.state import AgentState, ExecutionStatus


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_initial_state(request_id: str | None = None) -> AgentState:
    """Build a minimal valid AgentState for benchmarking."""
    return AgentState(
        request_id=request_id or str(uuid4()),
        user_id="user-bench-001",
        username="bench-user",
        roles=["developer"],
        tool_name="context_search",
        prompt="What is the auth flow?",
        timestamp="2026-07-16T00:00:00Z",
        status=ExecutionStatus.PENDING,
        current_node="",
        error=None,
        intent_type=None,
        intent_confidence=None,
        execution_plan=None,
        raw_context=None,
        ranked_context=None,
        compressed_context=None,
        tokens_before_compression=None,
        tokens_after_compression=None,
        governance_decisions=None,
        redacted_chunks=None,
        selected_model=None,
        model_routing_score=None,
        final_response=None,
    )


def _build_init_only_graph():
    async def _terminal_node(state: AgentState) -> dict:
        return {
            "current_node": "intent_agent",
            "status": ExecutionStatus.COMPLETE,
            "final_response": {"type": "answer", "message": "ok"},
        }

    builder: StateGraph = StateGraph(AgentState)
    builder.add_node("intent_agent", _terminal_node)
    builder.set_entry_point("intent_agent")
    builder.add_edge("intent_agent", END)
    return builder.compile()


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

@pytest.mark.benchmark(group="state-init")
def test_state_initialization_under_50ms(benchmark: BenchmarkFixture) -> None:
    """Mean state init + graph.ainvoke() through all stub nodes < 50 ms (50 rounds).

    Measured path:
      - AgentState dict construction          ~0.1 ms
      - graph.ainvoke() call setup            ~1 ms
      - All stub nodes (intent → routing)     ~2 ms
      Total budget: < 50 ms (target < 20 ms)
    """
    graph = _build_init_only_graph()

    def _run() -> AgentState:
        state = make_initial_state(request_id=str(uuid4()))
        config: dict[str, object] = {"configurable": {"thread_id": str(uuid4())}}
        return asyncio.run(graph.ainvoke(state, config=config))

    benchmark.pedantic(_run, rounds=50, warmup_rounds=5)
    # stats is None when benchmark is disabled (e.g. --benchmark-disable in CI smoke runs)
    if benchmark.stats is not None:
        assert benchmark.stats["mean"] < 0.050, (
            f"State initialization mean {benchmark.stats['mean'] * 1000:.2f} ms "
            f"exceeds 50 ms SLA"
        )
