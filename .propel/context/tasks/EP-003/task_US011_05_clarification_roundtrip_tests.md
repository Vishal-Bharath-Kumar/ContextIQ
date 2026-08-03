# TASK-US011-05 — End-to-End Clarification Round-Trip Integration Test

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US011-05 |
| User Story | US-011 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Testing |
| Priority | P1 |
| Points | 1 |
| Status | Draft |

## Description

Write integration tests that exercise the full clarification round-trip from ambiguous prompt submission to second-pass plan generation. Tests must cover: the happy path (clarification unlocks retrieval), the round-cap path (second low-confidence is forced to retrieval), and the expired-session error path. All LLM calls and Kafka publishers are mocked.

## Implementation Details

**Technology:** Python 3.11+, `pytest`, `pytest-asyncio`, `unittest.mock`

**File locations:**
- `tests/integration/test_clarification_roundtrip.py`

**Test suite layout:**

```
test_clarification_roundtrip.py
├── test_ambiguous_prompt_returns_clarification_needed
├── test_clarification_reply_produces_execution_plan
├── test_second_low_confidence_forced_to_retrieval
├── test_expired_session_returns_mcp_error
└── test_merged_prompt_passed_to_second_pass_intent_node
```

**Test 1 — Ambiguous prompt returns `clarification_needed`:**

```python
@pytest.mark.asyncio
async def test_ambiguous_prompt_returns_clarification_needed(
    mock_intent_chain,       # returns confidence=0.4, intent="general"
    mock_clar_chain,         # returns "What specific service are you referring to?"
    mock_kafka_publisher,
):
    response = await invoke_pipeline(prompt="Fix it", session_id="sess-001")

    assert response["type"] == "clarification_needed"
    assert response["question"].endswith("?")
    assert len(response["question"].split()) <= 50
    assert response["session_id"] == "sess-001"
    assert response["clarification_round"] == 0
```

**Test 2 — Clarification reply produces an execution plan:**

```python
@pytest.mark.asyncio
async def test_clarification_reply_produces_execution_plan(
    mock_intent_chain_high_confidence,   # second pass returns confidence=0.82, intent="debugging"
    mock_clar_chain,
    mock_checkpointer_with_state,        # pre-seeded with clarification_round=0 state
    mock_kafka_publisher,
):
    result = await invoke_clarification_reply(
        session_id     = "sess-001",
        clarification  = "The auth service throwing 401 on valid tokens in production",
    )

    assert result.get("execution_plan") is not None
    plan = result["execution_plan"]
    assert plan["sources"] == ["github", "stackoverflow", "jira"]
    assert plan["ranking_strategy"] == "hybrid"
    assert result.get("clarification_round") == 1
```

**Test 3 — Second low-confidence is forced to retrieval (round cap):**

```python
@pytest.mark.asyncio
async def test_second_low_confidence_forced_to_retrieval(
    mock_intent_chain_always_low,        # always returns confidence=0.3
    mock_checkpointer_with_round_1,      # pre-seeded with clarification_round=1
    mock_retrieval_node,
    mock_kafka_publisher,
):
    # Pipeline must not route to clarification again — must proceed to retrieval
    result = await invoke_clarification_reply(
        session_id    = "sess-002",
        clarification = "Still unclear",
    )

    # Retrieval ran (not clarification)
    assert mock_retrieval_node.called
    assert result.get("requires_clarification") is not True
```

**Test 4 — Expired session returns MCP error:**

```python
@pytest.mark.asyncio
async def test_expired_session_returns_mcp_error(mock_checkpointer_empty):
    with pytest.raises(McpError) as exc_info:
        await invoke_clarification_reply(
            session_id    = "sess-expired",
            clarification = "Some answer",
        )
    assert exc_info.value.error.code == INVALID_PARAMS
```

**Test 5 — Merged prompt passed to second-pass classifier:**

```python
@pytest.mark.asyncio
async def test_merged_prompt_passed_to_second_pass_intent_node(
    mock_intent_chain_capture,           # captures the prompt it receives
    mock_checkpointer_with_state,
    mock_kafka_publisher,
):
    await invoke_clarification_reply(
        session_id    = "sess-003",
        clarification = "The Kubernetes ingress controller",
    )

    captured_prompt = mock_intent_chain_capture.last_prompt
    assert "[Original request]"    in captured_prompt
    assert "[Clarification asked]" in captured_prompt
    assert "[User clarification]"  in captured_prompt
    assert "The Kubernetes ingress controller" in captured_prompt
```

**Shared fixtures (`conftest.py`):**

```python
@pytest.fixture
def mock_checkpointer_with_state(monkeypatch):
    """Seed the LangGraph checkpointer with a prior clarification state."""
    prior = AgentState(
        request_id           = "sess-001",
        prompt               = "Fix it",
        clarification_question = "What specific service are you referring to?",
        clarification_round  = 0,
        status               = ExecutionStatus.COMPLETE,
        requires_clarification = True,
        ...
    )
    monkeypatch.setattr("src.agents.worker.execute.graph.aget_state", AsyncMock(return_value=prior))
```

## Acceptance Criteria

- [ ] All 5 tests pass in CI with mocked LLM chains and Kafka publisher
- [ ] Test 2 asserts `execution_plan` is a non-`None` dict with `sources`, `ranking_strategy`, `token_budget_per_source`
- [ ] Test 3 asserts `retrieval_node` was called and no second clarification was issued
- [ ] Test 4 asserts `McpError` with `INVALID_PARAMS` code for expired sessions
- [ ] Test 5 asserts all three merge-template sections appear in the second-pass prompt
- [ ] No live LLM or Kafka calls in any test

## Dependencies

- TASK-US011-01 (clarification question generation)
- TASK-US011-02 (MCP response shape)
- TASK-US011-03 (round counter and cap routing)
- TASK-US011-04 (`clarification_reply` tool and `merge_prompt()`)
- TASK-US010-03 (`generate_execution_plan()` — asserted in Test 2)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All 5 integration tests pass in CI with `pytest --asyncio-mode=auto`
- [ ] Tests are in `tests/integration/` — not in `tests/unit/` — to distinguish from node-level unit tests
- [ ] No `ruff` lint errors; `mypy --strict` passes on the test file
