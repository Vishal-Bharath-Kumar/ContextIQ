# TASK-US020-04 — `FallbackInvoker`: Retry Orchestration with Circuit Breaker

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US020-04 |
| User Story | US-020 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `FallbackInvoker`, the component that wraps `LiteLLMInvoker` and orchestrates retries across an ordered `FallbackChain`. It checks the `ProviderCircuitBreaker` before each attempt, catches retryable errors, emits `FallbackEvent` log records, and returns `InvocationFailure` when the chain is exhausted. The fallback path adds ≤ 500 ms per retry (US-020 AC-6).

## Implementation Details

**Technology:** Python 3.11+, LiteLLM, `redis.asyncio`

**File locations:**
- `src/model_invoker/fallback_invoker.py` — `FallbackInvoker`
- `tests/model_invoker/test_fallback_invoker.py`

**`FallbackInvoker`:**

```python
# src/model_invoker/fallback_invoker.py
import logging
from src.model_invoker.invoker              import LiteLLMInvoker
from src.model_invoker.circuit_breaker      import ProviderCircuitBreaker, CircuitState
from src.model_invoker.error_classifier     import classify_error, extract_provider, FallbackEvent
from src.model_invoker.schemas.fallback_chain import FallbackChain, InvocationFailure
from src.model_invoker.schemas.llm_response   import LLMResponse
from src.model_invoker.config               import InvokerSettings
from src.model_registry.schemas.model_definition import LatencyTier

_log = logging.getLogger(__name__)

class FallbackInvoker:
    def __init__(
        self,
        invoker:         LiteLLMInvoker,
        circuit_breaker: ProviderCircuitBreaker,
        settings:        InvokerSettings | None = None,
    ) -> None:
        self._invoker         = invoker
        self._circuit_breaker = circuit_breaker
        self._settings        = settings or InvokerSettings()

    async def invoke(
        self,
        fallback_chain: FallbackChain,
        messages:       list[dict[str, str]],
        token_budget:   int,
        latency_tier:   LatencyTier = LatencyTier.MEDIUM,
        callbacks:      list | None = None,
    ) -> LLMResponse | InvocationFailure:
        max_attempts  = self._settings.max_fallback_attempts + 1  # primary + N fallbacks
        tried         = []
        last_error_code = "unknown"

        for model_id in fallback_chain.model_ids[:max_attempts]:
            provider = extract_provider(model_id)

            if not await self._circuit_breaker.is_available(provider):
                _log.warning(
                    "circuit_breaker_open",
                    extra={"model_id": model_id, "provider": provider},
                )
                tried.append(model_id)
                continue   # skip — treat open circuit as retryable; move to next candidate

            try:
                response = await self._invoker.invoke(
                    model_id     = model_id,
                    messages     = messages,
                    token_budget = token_budget,
                    latency_tier = latency_tier,
                    callbacks    = callbacks,
                )
                await self._circuit_breaker.record_success(provider)
                return response

            except Exception as exc:
                error_code = classify_error(exc)

                if error_code is None:
                    # Non-retryable (auth, bad request) — raise immediately; do not fallback
                    raise

                await self._circuit_breaker.record_failure(provider)
                tried.append(model_id)
                last_error_code = error_code.value

                # Determine next candidate for FallbackEvent (None if chain exhausted)
                next_idx       = fallback_chain.model_ids.index(model_id) + 1
                next_model_id  = (
                    fallback_chain.model_ids[next_idx]
                    if next_idx < len(fallback_chain.model_ids)
                    else None
                )
                attempt_number = len(tried)

                event = FallbackEvent(
                    attempt           = attempt_number,
                    primary_model_id  = model_id,
                    error_code        = error_code,
                    fallback_model_id = next_model_id,
                    provider          = provider,
                )
                _log.warning(
                    "fallback_attempt",
                    extra=event.model_dump(),
                )

        return InvocationFailure(
            message         = (
                f"All {len(tried)} model(s) in the fallback chain failed. "
                f"Last error: {last_error_code}."
            ),
            attempts        = len(tried),
            last_error_code = last_error_code,
            tried_model_ids = tried,
        )
```

**Latency budget per retry (US-020 AC-6: ≤ 500 ms additional per retry):**

The 500 ms budget covers:
1. `is_available()` Redis GET — typically < 1 ms
2. `LiteLLMInvoker.invoke()` round-trip — bounded by `InvokerSettings.timeout_fast_s` (10 s); the _overhead_ of the fallback decision itself is < 5 ms
3. `record_failure()` Redis pipeline — typically < 2 ms

The 500 ms constraint applies to the _fallback decision overhead_ (steps 1 + 3), not the LLM round-trip. CI benchmark tests use a `AsyncMock` `LiteLLMInvoker` with 0 ms latency to isolate the fallback machinery latency.

**Non-retryable error behaviour:**

`classify_error()` returns `None` for `AuthenticationError`, `BadRequestError`, and `ContextWindowExceededError`. These are re-raised immediately — no fallback, no circuit-breaker recording, no `FallbackEvent`. The caller (EP-007 answer node) receives the original exception.

**Skipped (open circuit) model IDs are still added to `tried`:**

This prevents an open circuit from silently inflating the available fallback budget. If 2 of 4 candidates have open circuits, the invoker can still try the other 2 within `max_fallback_attempts`.

## Acceptance Criteria

- [ ] Primary model failure → `FallbackEvent` emitted → next model tried
- [ ] All models exhausted → `InvocationFailure` returned with correct `attempts` count
- [ ] `FallbackInvoker` does not exceed `max_fallback_attempts + 1` total calls to `LiteLLMInvoker`
- [ ] Provider with open circuit is skipped (no `LiteLLMInvoker.invoke()` call for that model)
- [ ] `record_failure()` is called after each retryable error
- [ ] `record_success()` is called after a successful invocation
- [ ] Non-retryable `AuthenticationError` is re-raised without fallback
- [ ] `FallbackEvent` is logged with `primary_model_id`, `error_code`, and `fallback_model_id`

## Dependencies

- TASK-US020-01 (`FallbackChain`, `InvocationFailure`, `InvokerSettings.max_fallback_attempts`)
- TASK-US020-02 (`classify_error()`, `extract_provider()`, `FallbackEvent`)
- TASK-US020-03 (`ProviderCircuitBreaker.is_available()`, `record_failure()`, `record_success()`)
- TASK-US019-05 (`LiteLLMInvoker.invoke()` — wrapped here)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests: success on first attempt, success on second attempt, all exhausted → `InvocationFailure`, open circuit skipped, non-retryable re-raised, `record_success` called on success, `record_failure` called on retryable error
- [ ] CI benchmark: fallback overhead (excluding LLM latency) < 10 ms per attempt via `AsyncMock`
- [ ] `mypy --strict` passes; no `ruff` lint errors
