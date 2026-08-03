# TASK-US019-05 — `LiteLLMInvoker`: Unified Model Invocation via LiteLLM

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US019-05 |
| User Story | US-019 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `LiteLLMInvoker`, the component that executes the LLM call for the selected model using the LiteLLM unified API. The invoker reads `selected_model_id` from `AgentState`, constructs the request with the appropriate timeout (derived from `LatencyTier`), and returns a frozen `LLMResponse` model. This is the integration point for TR-005 (LiteLLM) and serves as the seam consumed by EP-007 (Answer Generation).

## Implementation Details

**Technology:** Python 3.11+, LiteLLM (`>=1.30`), Pydantic v2

**File locations:**
- `src/model_invoker/schemas/llm_response.py` — `LLMResponse` frozen model
- `src/model_invoker/invoker.py` — `LiteLLMInvoker`
- `src/model_invoker/config.py` — `InvokerSettings`
- `tests/model_invoker/test_litellm_invoker.py` — tests with `AsyncMock`

**`LLMResponse`:**

```python
# src/model_invoker/schemas/llm_response.py
from pydantic import BaseModel, ConfigDict

class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id:     str
    content:      str
    input_tokens:  int
    output_tokens: int
    finish_reason: str   # "stop" | "length" | "tool_calls" | "error"
```

**`InvokerSettings`:**

```python
# src/model_invoker/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.model_registry.schemas.model_definition import LatencyTier

class InvokerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVOKER_", env_file=".env", extra="ignore")

    timeout_fast_s:   float = 10.0   # LatencyTier.FAST — p95 < 500 ms; allow 10 s for safety
    timeout_medium_s: float = 30.0   # LatencyTier.MEDIUM — p95 < 2 s; allow 30 s
    timeout_slow_s:   float = 120.0  # LatencyTier.SLOW — o1-class; allow 120 s

LATENCY_TIER_TIMEOUT: dict[LatencyTier, float] = {}   # populated from InvokerSettings at module init
```

**`LiteLLMInvoker`:**

```python
# src/model_invoker/invoker.py
from typing import Sequence
import litellm
from src.model_invoker.schemas.llm_response import LLMResponse
from src.model_invoker.config               import InvokerSettings, LATENCY_TIER_TIMEOUT
from src.model_registry.schemas.model_definition import LatencyTier

class LiteLLMInvoker:
    def __init__(self, settings: InvokerSettings | None = None) -> None:
        self._settings = settings or InvokerSettings()
        LATENCY_TIER_TIMEOUT.update({
            LatencyTier.FAST:   self._settings.timeout_fast_s,
            LatencyTier.MEDIUM: self._settings.timeout_medium_s,
            LatencyTier.SLOW:   self._settings.timeout_slow_s,
        })

    async def invoke(
        self,
        model_id:     str,
        messages:     list[dict[str, str]],   # [{"role": "user", "content": "..."}]
        token_budget: int,
        latency_tier: LatencyTier = LatencyTier.MEDIUM,
        callbacks:    list | None = None,     # Langfuse CallbackHandler list
    ) -> LLMResponse:
        timeout = LATENCY_TIER_TIMEOUT[latency_tier]

        response = await litellm.acompletion(
            model     = model_id,
            messages  = messages,
            max_tokens = token_budget,
            timeout   = timeout,
            callbacks = callbacks or [],
        )

        choice = response.choices[0]
        usage  = response.usage

        return LLMResponse(
            model_id      = model_id,
            content       = choice.message.content or "",
            input_tokens  = usage.prompt_tokens,
            output_tokens = usage.completion_tokens,
            finish_reason = choice.finish_reason or "stop",
        )
```

**`AgentState` integration note:**

`LiteLLMInvoker` is not a LangGraph node — it is a service called by the answer generation node (EP-007). The bridge between US-019 and EP-007 is:
- EP-007 reads `state["selected_model_id"]` and `state["execution_plan"]["token_budget_total"]`
- EP-007 instantiates `LiteLLMInvoker` and calls `invoke(model_id=selected_model_id, ...)`

The invoker itself has no dependency on `AgentState` and can be unit-tested independently.

**LiteLLM API key handling:**

LiteLLM reads provider API keys from environment variables following its own convention (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). The invoker does NOT handle keys directly — they are injected via the deployment environment. This avoids credential leakage through application code.

**`callbacks` parameter:**

Pass the `CallbackHandler` from `make_langfuse_handler()` (TASK-US017-05) as `callbacks=[langfuse_handler]`. LiteLLM calls the Langfuse handler automatically for token cost tracking via its native callback mechanism.

## Acceptance Criteria

- [ ] `LiteLLMInvoker.invoke()` returns an `LLMResponse` with non-empty `content`
- [ ] `input_tokens` and `output_tokens` match the `usage` object from LiteLLM's response
- [ ] Timeout is derived from `LatencyTier`; `FAST` uses a shorter timeout than `SLOW`
- [ ] `callbacks` list is forwarded to `litellm.acompletion()` unchanged
- [ ] Invoker does not access or log API keys from any source
- [ ] Tests use `AsyncMock` for `litellm.acompletion`; no live LLM calls in CI

## Dependencies

- TASK-US019-01 (`LatencyTier` — drives timeout selection)
- TASK-US019-04 (`routing_node()` writes `selected_model_id` to state; EP-007 reads it)
- TASK-US017-05 (`make_langfuse_handler()` — `CallbackHandler` passed as `callbacks`)
- TASK-US010-02 (`token_budget_total` from `ExecutionPlan` — `max_tokens` argument)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests: successful invocation, `finish_reason="length"` on token overflow, timeout mapped correctly per tier, `callbacks` forwarded
- [ ] `mypy --strict` passes; no `ruff` lint errors
- [ ] LiteLLM version pinned: `litellm>=1.30` in `requirements.txt` / `pyproject.toml`
