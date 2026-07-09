# TASK-US005-05 — Concurrent Graph Isolation and 50 ms Initialization Benchmark

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US005-05 |
| User Story | US-005 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | QA / Performance |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Validate that concurrent graph invocations from the same user execute in fully independent LangGraph instances with no shared state, and that the state initialization path (state hydration + first checkpoint write) completes within the 50 ms SLA.

## Implementation Details

**Technology:** Python 3.11+, `pytest`, `pytest-asyncio`, `pytest-benchmark`, `fakeredis`

**File locations:**
- `tests/agents/test_concurrent_graph_isolation.py` — concurrency isolation tests
- `tests/agents/test_state_init_performance.py` — initialization benchmark

**What "state initialization" covers (the 50 ms budget):**

| Step | Expected time |
|---|---|
| `AgentState` dict construction | ~0.1 ms |
| `graph.ainvoke()` call setup | ~1 ms |
| First checkpoint write to Redis | ~5–15 ms (local Redis) |
| First node (`intent_agent`) stub entry | ~0.5 ms |
| **Total** | **< 20 ms** (well within 50 ms) |

**Benchmark test:**
```python
@pytest.mark.asyncio
@pytest.mark.benchmark(group="state-init")
async def test_state_initialization_under_50ms(benchmark, compiled_graph, fake_redis):
    """State init + first checkpoint write must complete in < 50 ms"""
    initial_state = make_initial_state()
    config = {"configurable": {"thread_id": str(uuid4())}}

    async def _invoke():
        # Measure up to and including first node entry (stub returns immediately)
        return await compiled_graph.ainvoke(initial_state, config=config)

    result = await benchmark.pedantic(_invoke, rounds=50, warmup_rounds=5)
    assert benchmark.stats["mean"] < 0.050   # 50 ms
```

**Concurrent isolation test:**
```python
@pytest.mark.asyncio
async def test_concurrent_requests_from_same_user_are_isolated():
    user_id = "user-001"
    request_ids = [str(uuid4()) for _ in range(10)]

    async def invoke_one(rid: str) -> AgentState:
        state = make_initial_state(request_id=rid, user_id=user_id, prompt=f"prompt-{rid}")
        config = {"configurable": {"thread_id": rid}}
        return await compiled_graph.ainvoke(state, config=config)

    results = await asyncio.gather(*[invoke_one(rid) for rid in request_ids])

    # Each result has its own request_id — no cross-contamination
    result_request_ids = [r["request_id"] for r in results]
    assert result_request_ids == request_ids

    # Each result has the correct prompt (no prompt from another concurrent invocation)
    for i, r in enumerate(results):
        assert r["prompt"] == f"prompt-{request_ids[i]}"
```

**State bleed detection test:**
```python
@pytest.mark.asyncio
async def test_state_mutation_in_one_graph_does_not_affect_another():
    """A node that mutates state in graph A must not affect state in graph B"""
    state_a = make_initial_state(request_id="a", prompt="prompt-A")
    state_b = make_initial_state(request_id="b", prompt="prompt-B")

    # Run both graphs concurrently; node in A sets intent_type = "debugging"
    result_a, result_b = await asyncio.gather(
        compiled_graph.ainvoke(state_a, config={"configurable": {"thread_id": "a"}}),
        compiled_graph.ainvoke(state_b, config={"configurable": {"thread_id": "b"}}),
    )

    # B must never see A's intent_type
    assert result_b.get("intent_type") != "debugging"
    assert result_b["prompt"] == "prompt-B"
```

**Redis key isolation verification:**
```python
async def test_each_graph_writes_to_own_checkpoint_namespace(fake_redis):
    rid_a, rid_b = str(uuid4()), str(uuid4())
    await asyncio.gather(invoke(rid_a), invoke(rid_b))

    keys_a = await fake_redis.keys(f"checkpoint:{rid_a}*")
    keys_b = await fake_redis.keys(f"checkpoint:{rid_b}*")

    assert len(keys_a) > 0
    assert len(keys_b) > 0
    # No overlap in key namespaces
    assert not set(keys_a) & set(keys_b)
```

## Acceptance Criteria

- [ ] Benchmark: mean state initialization time < 50 ms across 50 iterations (asserted in CI)
- [ ] 10 concurrent invocations from the same `user_id` complete with distinct `request_id` values in their state
- [ ] Prompt set in graph A is never visible in graph B's final state (state bleed test)
- [ ] Redis checkpoint keys for concurrent requests are namespaced independently (no key overlap)
- [ ] All tests pass with `fakeredis` (no real Redis required in CI)

## Dependencies

- TASK-US005-01 (`AgentState` and compiled graph)
- TASK-US005-02 (`make_initial_state()` test helper follows `ExecuteRequest` hydration logic)
- TASK-US005-03 (checkpointer injected into compiled graph)

## Definition of Done

- [ ] `pytest-benchmark` and `pytest-asyncio` configured in `pyproject.toml` with `asyncio_mode = "auto"`
- [ ] Benchmark results stored as CI artifact; regression alert if mean > 50 ms
- [ ] Concurrency tests tagged `@pytest.mark.concurrency` and run in a dedicated CI job
- [ ] All 4 test cases pass with zero failures across 10 consecutive CI runs
