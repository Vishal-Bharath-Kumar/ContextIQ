# TASK-US020-01 — `FallbackChain` Schema, `FallbackSettings`, and `ModelRouter` Extension

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US020-01 |
| User Story | US-020 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the `FallbackChain` frozen Pydantic model (an ordered list of candidate model IDs), add `FallbackSettings` constants (`MAX_FALLBACK_ATTEMPTS=3`), extend `ModelRouter` with a `build_fallback_chain()` method that returns the top-N scored candidates instead of only the winner, and add `fallback_chain` to `AgentState` for downstream consumption by `FallbackInvoker` (TASK-US020-04).

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/model_invoker/schemas/fallback_chain.py` — `FallbackChain`, `InvocationFailure`
- `src/model_invoker/config.py` — `FallbackSettings` (extend `InvokerSettings`)
- `src/model_router/router.py` — `ModelRouter.build_fallback_chain()` (add method; do not alter `select()`)
- `src/agents/state.py` — `AgentState.fallback_chain` extension (patch only)
- `tests/model_router/test_fallback_chain.py`

**`FallbackChain` and `InvocationFailure`:**

```python
# src/model_invoker/schemas/fallback_chain.py
from pydantic import BaseModel, ConfigDict, Field

class FallbackChain(BaseModel):
    """Ordered list of model IDs to try, primary first."""
    model_config = ConfigDict(frozen=True)

    model_ids:   list[str] = Field(min_length=1)
    intent_type: str


class InvocationFailure(BaseModel):
    """Returned when all fallback attempts are exhausted."""
    model_config = ConfigDict(frozen=True)

    message:          str   # human-readable; surfaced to API caller
    attempts:         int   # number of models tried (≤ MAX_FALLBACK_ATTEMPTS + 1)
    last_error_code:  str   # final RetryableErrorCode value
    tried_model_ids:  list[str]
```

**`FallbackSettings` — extend `InvokerSettings`:**

```python
# src/model_invoker/config.py  — extend existing InvokerSettings; do NOT replace
from pydantic_settings import BaseSettings, SettingsConfigDict

class InvokerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVOKER_", env_file=".env", extra="ignore")

    timeout_fast_s:        float = 10.0
    timeout_medium_s:      float = 30.0
    timeout_slow_s:        float = 120.0
    max_fallback_attempts: int   = 3     # US-020 AC-3: max 3 fallbacks after primary
    fallback_chain_size:   int   = 4     # top-N models to pre-select (primary + 3 fallbacks)
```

**`ModelRouter.build_fallback_chain()` — extend existing class:**

```python
# src/model_router/router.py  — add method to ModelRouter; do NOT alter select()
from src.model_invoker.schemas.fallback_chain import FallbackChain
from src.model_invoker.config                 import InvokerSettings

async def build_fallback_chain(
    self,
    intent_type: str,
    settings:    InvokerSettings | None = None,
) -> FallbackChain | None:
    """
    Return an ordered FallbackChain of up to fallback_chain_size model IDs.
    Returns None if the scored candidate list is empty.
    """
    n = (settings or InvokerSettings()).fallback_chain_size

    # Reuse existing scoring/cache logic — read full scored list, not just [0]
    cached = await self._scored_model_cache.get(intent_type)
    if cached is None:
        # Cold path — populate cache via select(), then re-read
        await self.select(intent_type=intent_type)
        cached = await self._scored_model_cache.get(intent_type)

    if not cached:
        return None

    return FallbackChain(
        model_ids   = [s.model_id for s in cached[:n]],
        intent_type = intent_type,
    )
```

`select()` remains the single-winner shortcut used by `routing_node()`; `build_fallback_chain()` is the multi-candidate path used by the fallback invoker.

**`AgentState` extension:**

```python
# src/agents/state.py  — patch only
class AgentState(TypedDict, total=False):
    ...                                           # existing fields unchanged
    fallback_chain: list[str] | None              # ordered model IDs; primary is [0]
```

## Acceptance Criteria

- [ ] `FallbackChain(model_ids=[], intent_type="general")` raises `ValidationError` (`min_length=1`)
- [ ] `ModelRouter.build_fallback_chain()` returns at most `fallback_chain_size` model IDs
- [ ] When `ScoredModelCache` is cold, `build_fallback_chain()` populates it via `select()` before building the chain
- [ ] `InvokerSettings.max_fallback_attempts` defaults to `3`; overridable via `INVOKER_MAX_FALLBACK_ATTEMPTS`
- [ ] `AgentState.fallback_chain` defaults to `None`

## Dependencies

- TASK-US019-02 (`ScoredModelCache`, `ModelScore`)
- TASK-US019-03 (`ModelRouter` class — method added here)
- TASK-US019-05 (`InvokerSettings` — extended here; `LLMResponse` / `InvocationFailure` same module)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests: `build_fallback_chain()` hot path, cold path with cache population, empty result → `None`, chain truncation to `fallback_chain_size`
- [ ] `mypy --strict` passes; no `ruff` lint errors
