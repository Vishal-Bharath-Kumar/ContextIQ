# TASK-US020-02 — Retryable Error Classifier and `FallbackEvent` Model

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US020-02 |
| User Story | US-020 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `classify_error()` — a pure function that inspects a LiteLLM exception and returns a `RetryableErrorCode` when the error warrants a fallback attempt, or `None` for non-retryable failures. Also define `FallbackEvent`, the structured log record emitted per fallback attempt, satisfying US-020 AC-4.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, LiteLLM (`>=1.30`)

**File locations:**
- `src/model_invoker/error_classifier.py` — `RetryableErrorCode`, `classify_error()`
- `src/model_invoker/schemas/fallback_event.py` — `FallbackEvent`
- `tests/model_invoker/test_error_classifier.py`

**`RetryableErrorCode`:**

```python
# src/model_invoker/error_classifier.py
from enum import StrEnum

class RetryableErrorCode(StrEnum):
    HTTP_5XX       = "http_5xx"      # 500, 502, 503, 504
    RATE_LIMITED   = "rate_limited"  # HTTP 429
    TIMEOUT        = "timeout"       # asyncio.TimeoutError or LiteLLM APITimeoutError
```

**LiteLLM exception hierarchy** (relevant subset from `litellm.exceptions`):

| Exception class | Maps to |
|---|---|
| `litellm.exceptions.APIError` with status 5xx | `HTTP_5XX` |
| `litellm.exceptions.RateLimitError` | `RATE_LIMITED` |
| `litellm.exceptions.APITimeoutError` | `TIMEOUT` |
| `asyncio.TimeoutError` | `TIMEOUT` |
| `litellm.exceptions.AuthenticationError` | `None` — not retryable |
| `litellm.exceptions.BadRequestError` | `None` — not retryable |
| `litellm.exceptions.ContextWindowExceededError` | `None` — not retryable |

**`classify_error()`:**

```python
import asyncio
import litellm.exceptions as lx

def classify_error(exc: BaseException) -> RetryableErrorCode | None:
    """
    Return RetryableErrorCode if the error warrants a fallback, else None.
    Non-retryable errors (auth, bad request, context window) are surfaced immediately.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return RetryableErrorCode.TIMEOUT
    if isinstance(exc, lx.APITimeoutError):
        return RetryableErrorCode.TIMEOUT
    if isinstance(exc, lx.RateLimitError):
        return RetryableErrorCode.RATE_LIMITED
    if isinstance(exc, lx.APIError):
        status = getattr(exc, "status_code", None)
        if status is not None and 500 <= status <= 599:
            return RetryableErrorCode.HTTP_5XX
    # AuthenticationError, BadRequestError, ContextWindowExceededError — not retryable
    return None
```

`classify_error()` never raises — exceptions in the classifier itself must not propagate to the invoker.

**`FallbackEvent`:**

```python
# src/model_invoker/schemas/fallback_event.py
from pydantic import BaseModel, ConfigDict
from src.model_invoker.error_classifier import RetryableErrorCode

class FallbackEvent(BaseModel):
    """Structured log record emitted per fallback attempt (US-020 AC-4)."""
    model_config = ConfigDict(frozen=True)

    attempt:          int              # 1-based; 1 = first fallback after primary failure
    primary_model_id: str              # model that failed
    error_code:       RetryableErrorCode
    fallback_model_id: str | None      # next model to be tried; None if chain exhausted
    provider:         str              # extracted from model_id (prefix before '/')
```

**Provider extraction:**

```python
def extract_provider(model_id: str) -> str:
    """
    'anthropic/claude-3-haiku' → 'anthropic'
    'gpt-4o-mini'              → 'openai'  (LiteLLM default provider for gpt-* models)
    """
    if "/" in model_id:
        return model_id.split("/")[0]
    # LiteLLM maps bare model names to a default provider; use 'openai' as fallback
    return "openai"
```

`FallbackEvent` is emitted by `FallbackInvoker` (TASK-US020-04) and written to the structured logger (`structlog` or standard logging) — it is NOT stored in `AgentState`.

## Acceptance Criteria

- [ ] `classify_error(RateLimitError())` returns `RetryableErrorCode.RATE_LIMITED`
- [ ] `classify_error(APIError(status_code=503))` returns `RetryableErrorCode.HTTP_5XX`
- [ ] `classify_error(asyncio.TimeoutError())` returns `RetryableErrorCode.TIMEOUT`
- [ ] `classify_error(AuthenticationError())` returns `None`
- [ ] `classify_error(ContextWindowExceededError())` returns `None`
- [ ] `extract_provider("anthropic/claude-3-haiku")` returns `"anthropic"`
- [ ] `extract_provider("gpt-4o-mini")` returns `"openai"`
- [ ] `FallbackEvent` constructs without error; `fallback_model_id=None` valid when chain exhausted

## Dependencies

- TASK-US020-01 (`FallbackChain`, `InvocationFailure` — sibling module in `model_invoker`)
- TASK-US019-05 (`LiteLLMInvoker` — raises LiteLLM exceptions caught here)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] 100% branch coverage on `classify_error()` for all 7 exception types
- [ ] `mypy --strict` passes; no `ruff` lint errors
