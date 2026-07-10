# TASK-US020-05 — `routing_node` Extension: Fallback Chain Population + Integration Tests

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US020-05 |
| User Story | US-020 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Extend `routing_node()` to call `ModelRouter.build_fallback_chain()` and write the ordered model ID list to `AgentState.fallback_chain`. Write the integration test suite covering all 6 US-020 acceptance criteria, combining `FallbackInvoker`, `ProviderCircuitBreaker`, and mocked LiteLLM responses to verify end-to-end fallback behaviour and the ≤ 500 ms-per-retry latency constraint.

## Implementation Details

**Technology:** Python 3.11+, LangGraph, pytest-asyncio, `fakeredis.aioredis`, `AsyncMock`

**File locations:**
- `src/agents/nodes/routing_node.py` — extend `routing_node()` (patch only; do NOT rewrite)
- `tests/model_invoker/test_fallback_integration.py` — all 6 AC-level integration tests

**`routing_node()` extension:**

```python
# src/agents/nodes/routing_node.py  — add fallback chain build after existing select() call
# Insert after the `selection = await router.select(...)` block:

    fallback = await router.build_fallback_chain(intent_type=intent_type)
    fallback_chain_ids = fallback.model_ids if fallback is not None else [selected_model_id]

    # ... existing OTel + Langfuse blocks unchanged ...

    return {
        **state,
        "selected_model_id": selected_model_id,
        "routing_score":     routing_score,
        "fallback_chain":    fallback_chain_ids,   # new field
    }
```

`fallback_chain_ids[0]` is always `selected_model_id` (the top-scored model), so downstream nodes can use either field without divergence.

**Integration test structure:**

```python
# tests/model_invoker/test_fallback_integration.py
import asyncio, pytest
from unittest.mock import AsyncMock, patch
import fakeredis.aioredis as fakeredis
import litellm.exceptions as lx

from src.model_invoker.fallback_invoker     import FallbackInvoker
from src.model_invoker.circuit_breaker      import ProviderCircuitBreaker, CircuitState
from src.model_invoker.invoker              import LiteLLMInvoker
from src.model_invoker.schemas.fallback_chain import FallbackChain, InvocationFailure
from src.model_invoker.schemas.llm_response   import LLMResponse
from src.model_invoker.config               import InvokerSettings
from src.model_registry.schemas.model_definition import LatencyTier

CHAIN = FallbackChain(
    model_ids   = ["gpt-4o-mini", "anthropic/claude-3-haiku", "mistral/mistral-7b", "openai/gpt-3.5-turbo"],
    intent_type = "code_generation",
)
MESSAGES     = [{"role": "user", "content": "Write a hello-world function."}]
TOKEN_BUDGET = 512

@pytest.fixture
async def redis():
    return fakeredis.FakeRedis()

@pytest.fixture
def settings():
    return InvokerSettings(max_fallback_attempts=3, circuit_failure_threshold=5, circuit_window_s=60)
```

**AC-1 — Ordered fallback list:**

```python
async def test_fallback_chain_order(redis, settings):
    """Primary [0] is tried first; second [1] on primary failure."""
    invoke_mock = AsyncMock(side_effect=[
        lx.RateLimitError("429", llm_provider="openai", model="gpt-4o-mini", response=None),
        LLMResponse(model_id="anthropic/claude-3-haiku", content="hi", input_tokens=5, output_tokens=3, finish_reason="stop"),
    ])
    invoker = LiteLLMInvoker()
    invoker.invoke = invoke_mock
    cb = ProviderCircuitBreaker(redis, settings)
    fi = FallbackInvoker(invoker, cb, settings)

    result = await fi.invoke(CHAIN, MESSAGES, TOKEN_BUDGET)
    assert isinstance(result, LLMResponse)
    assert result.model_id == "anthropic/claude-3-haiku"
    assert invoke_mock.call_count == 2
```

**AC-2 — HTTP 5xx / 429 / timeout triggers fallback:**

```python
@pytest.mark.parametrize("exc", [
    lx.APIError("503", llm_provider="openai", model="gpt-4o-mini", status_code=503, response=None),
    lx.RateLimitError("429", llm_provider="openai", model="gpt-4o-mini", response=None),
    lx.APITimeoutError(message="timeout", model="gpt-4o-mini", llm_provider="openai", request=None),
])
async def test_retryable_errors_trigger_fallback(exc, redis, settings):
    success = LLMResponse(model_id="anthropic/claude-3-haiku", content="ok", input_tokens=5, output_tokens=2, finish_reason="stop")
    invoke_mock = AsyncMock(side_effect=[exc, success])
    ...  # assert result is LLMResponse, invoke_mock.call_count == 2
```

**AC-3 — Maximum 3 fallback attempts:**

```python
async def test_max_fallback_attempts_exhausted(redis, settings):
    """4 models, all fail — InvocationFailure with attempts=4 (primary + 3 fallbacks)."""
    invoke_mock = AsyncMock(side_effect=[
        lx.RateLimitError(...) for _ in range(4)
    ])
    ...
    result = await fi.invoke(CHAIN, MESSAGES, TOKEN_BUDGET)
    assert isinstance(result, InvocationFailure)
    assert result.attempts == 4
    assert len(result.tried_model_ids) == 4
```

**AC-4 — Fallback event logged with primary model ID, error code, fallback model ID:**

```python
async def test_fallback_event_logged(redis, settings, caplog):
    ...
    with caplog.at_level(logging.WARNING, logger="src.model_invoker.fallback_invoker"):
        await fi.invoke(...)
    assert "fallback_attempt" in caplog.text
    assert "gpt-4o-mini" in caplog.text
    assert "rate_limited" in caplog.text
```

**AC-5 — Circuit breaker opens after 5 consecutive failures within 60 s:**

```python
async def test_circuit_breaker_opens_after_threshold(redis, settings):
    cb = ProviderCircuitBreaker(redis, settings)
    for _ in range(settings.circuit_failure_threshold):
        state = await cb.record_failure("openai")
    assert state == CircuitState.OPEN
    assert not await cb.is_available("openai")
```

**AC-6 — Fallback adds ≤ 500 ms additional latency per retry:**

```python
async def test_fallback_overhead_under_500ms(redis, settings):
    """Measure FallbackInvoker overhead excluding LLM latency using 0-delay AsyncMock."""
    invoke_mock = AsyncMock(side_effect=[
        lx.RateLimitError(...),
        LLMResponse(model_id="anthropic/claude-3-haiku", content="ok", input_tokens=5, output_tokens=2, finish_reason="stop"),
    ])
    ...
    import time
    t0 = time.perf_counter()
    await fi.invoke(FallbackChain(model_ids=["gpt-4o-mini", "anthropic/claude-3-haiku"], intent_type="general"), MESSAGES, TOKEN_BUDGET)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 500, f"Fallback overhead {elapsed_ms:.1f} ms exceeded 500 ms budget"
```

## Acceptance Criteria

- [ ] `routing_node()` writes `fallback_chain` to `AgentState` — list has ≥ 1 entry
- [ ] `fallback_chain[0]` always equals `selected_model_id`
- [ ] Integration tests for all 6 US-020 ACs pass in CI
- [ ] Circuit breaker test uses `fakeredis` `time_travel` for TTL expiry — no `sleep()` calls
- [ ] Fallback overhead benchmark < 500 ms with mocked `LiteLLMInvoker`

## Dependencies

- TASK-US020-01 (`FallbackChain`, `AgentState.fallback_chain`, `ModelRouter.build_fallback_chain()`)
- TASK-US020-02 (`classify_error()`, `FallbackEvent`)
- TASK-US020-03 (`ProviderCircuitBreaker`)
- TASK-US020-04 (`FallbackInvoker`)
- TASK-US019-04 (`routing_node()` — extended here; do NOT rewrite)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All 6 AC-level integration tests pass
- [ ] No `time.sleep()` in tests — use `fakeredis` time travel or mocking for TTL
- [ ] `mypy --strict` passes; no `ruff` lint errors
