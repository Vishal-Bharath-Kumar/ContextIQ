"""TASK-US005-05: Concurrent graph isolation tests.

Validates that concurrent LangGraph invocations from the same user execute in
fully independent instances with no shared state, and that checkpoint keys are
namespaced by thread_id with no cross-request overlap.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from src.agents.graph import build_graph
from src.agents.state import AgentState, ExecutionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_initial_state(
    *,
    request_id: str | None = None,
    user_id: str = "user-001",
    prompt: str = "What is the auth flow?",
) -> AgentState:
    """Build a minimal valid AgentState matching ExecuteRequest hydration logic."""
    return AgentState(
        request_id=request_id or str(uuid4()),
        user_id=user_id,
        username="alice",
        roles=["developer"],
        tool_name="context_search",
        prompt=prompt,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def compiled_graph() -> object:
    """Compiled graph without checkpointer — no Redis required in CI."""
    return build_graph()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.concurrency
async def test_concurrent_requests_from_same_user_are_isolated(
    compiled_graph: object,
) -> None:
    """10 concurrent invocations from the same user_id complete with distinct request_ids.

    Each result must carry its own request_id and prompt — no cross-contamination.
    """
    user_id = "user-001"
    request_ids = [str(uuid4()) for _ in range(10)]

    async def invoke_one(rid: str) -> AgentState:
        state = make_initial_state(request_id=rid, user_id=user_id, prompt=f"prompt-{rid}")
        config: dict[str, object] = {"configurable": {"thread_id": rid}}
        return await compiled_graph.ainvoke(state, config=config)  # type: ignore[union-attr]

    results: list[AgentState] = await asyncio.gather(*[invoke_one(rid) for rid in request_ids])

    result_request_ids = [r["request_id"] for r in results]
    assert result_request_ids == request_ids, (
        f"request_id mismatch: expected {request_ids}, got {result_request_ids}"
    )

    for i, r in enumerate(results):
        assert r["prompt"] == f"prompt-{request_ids[i]}", (
            f"Prompt contamination at index {i}: expected 'prompt-{request_ids[i]}', "
            f"got '{r['prompt']}'"
        )


@pytest.mark.concurrency
async def test_state_mutation_in_one_graph_does_not_affect_another(
    compiled_graph: object,
) -> None:
    """State mutations in graph A must not bleed into graph B running concurrently."""
    state_a = make_initial_state(request_id="req-a", prompt="prompt-A")
    state_b = make_initial_state(request_id="req-b", prompt="prompt-B")

    result_a, result_b = await asyncio.gather(
        compiled_graph.ainvoke(  # type: ignore[union-attr]
            state_a, config={"configurable": {"thread_id": "req-a"}}
        ),
        compiled_graph.ainvoke(  # type: ignore[union-attr]
            state_b, config={"configurable": {"thread_id": "req-b"}}
        ),
    )

    # B must never see A's fields
    assert result_b.get("intent_type") != "debugging", (
        "intent_type from graph A bled into graph B"
    )
    assert result_b["prompt"] == "prompt-B", (
        f"Graph B prompt contaminated: got '{result_b['prompt']}'"
    )
    assert result_a["prompt"] == "prompt-A", (
        f"Graph A prompt contaminated: got '{result_a['prompt']}'"
    )
    # request_id must remain per-invocation
    assert result_a["request_id"] == "req-a"
    assert result_b["request_id"] == "req-b"


@pytest.mark.concurrency
async def test_each_graph_writes_to_own_checkpoint_namespace() -> None:
    """Checkpoint storage keys for concurrent requests must not overlap.

    Uses MemorySaver (in-memory, no Redis required) to verify that each
    thread_id writes into its own namespace with zero cross-request key
    overlap.
    """
    from langgraph.checkpoint.memory import MemorySaver

    memory: MemorySaver = MemorySaver()
    graph = build_graph(checkpointer=memory)

    rid_a = str(uuid4())
    rid_b = str(uuid4())

    await asyncio.gather(
        graph.ainvoke(
            make_initial_state(request_id=rid_a),
            config={"configurable": {"thread_id": rid_a}},
        ),
        graph.ainvoke(
            make_initial_state(request_id=rid_b),
            config={"configurable": {"thread_id": rid_b}},
        ),
    )

    # MemorySaver stores checkpoints keyed by thread_id at the top level
    keys_a = {k for k in memory.storage if k == rid_a}
    keys_b = {k for k in memory.storage if k == rid_b}

    assert len(keys_a) > 0, f"No checkpoint keys found for thread_id={rid_a!r}"
    assert len(keys_b) > 0, f"No checkpoint keys found for thread_id={rid_b!r}"
    assert not (keys_a & keys_b), (
        f"Checkpoint key overlap detected between {rid_a!r} and {rid_b!r}: "
        f"{keys_a & keys_b}"
    )
