# TASK-US017-02 — `SummarizationSettings` Config (Threshold and Model Name)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US017-02 |
| User Story | US-017 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / Config |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define `SummarizationSettings`, the Pydantic settings model that exposes the token threshold, model name, and target compression ratio as admin-configurable values. The model name field provides the EP-006 Dynamic Model Router integration seam — Phase 1 defaults to `gpt-4o-mini` directly; EP-006 will replace this with a router-resolved model identifier without requiring code changes.

## Implementation Details

**Technology:** Python 3.11+, `pydantic-settings`

**File locations:**
- `src/compression/summarization/settings.py` — `SummarizationSettings` and module-level singleton
- `tests/compression/summarization/test_settings.py`

**`SummarizationSettings`:**

```python
# src/compression/summarization/settings.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SUMMARIZATION_TOKEN_THRESHOLD: int   = 500    # US-017 AC-1: chunks above this are summarised
SUMMARIZATION_TARGET_RATIO:    float = 0.40   # target: summary ≤ 40% of original tokens (60% reduction)
SUMMARIZATION_MAX_OUTPUT_TOKENS: int = 400    # LLM max_tokens cap — prevents runaway cost

class SummarizationSettings(BaseSettings):
    """Configuration for LLM-based chunk summarisation.

    Environment variables (all prefixed SUMMARIZATION_):
        TOKEN_THRESHOLD     — int ≥ 1, default 500
        MODEL_NAME          — string, default "gpt-4o-mini"
                              Set to a model-router endpoint when EP-006 is available.
        TARGET_RATIO        — float in (0.0, 1.0), default 0.40
        MAX_OUTPUT_TOKENS   — int ≥ 50, default 400
        MAX_CONCURRENT      — int ≥ 1, default 10 (asyncio.gather concurrency cap)
        LANGFUSE_ENABLED    — bool, default True
    """
    token_threshold:   int   = Field(default=SUMMARIZATION_TOKEN_THRESHOLD,   ge=1)
    model_name:        str   = Field(default="gpt-4o-mini")
    target_ratio:      float = Field(default=SUMMARIZATION_TARGET_RATIO,      gt=0.0, lt=1.0)
    max_output_tokens: int   = Field(default=SUMMARIZATION_MAX_OUTPUT_TOKENS, ge=50)
    max_concurrent:    int   = Field(default=10,                               ge=1)
    langfuse_enabled:  bool  = Field(default=True)

    model_config = SettingsConfigDict(
        env_prefix = "SUMMARIZATION_",
        env_file   = ".env",
    )

_settings: SummarizationSettings | None = None

def get_summarization_settings() -> SummarizationSettings:
    global _settings
    if _settings is None:
        _settings = SummarizationSettings()
    return _settings
```

**EP-006 model router integration seam:**

When EP-006 is delivered, the model router will resolve `model_name` to a provider-specific model based on cost/quality trade-offs. The integration point is:

```python
# Future EP-006 usage (no code change needed in SummarizationSettings):
# settings.model_name = await model_router.resolve("summarization", budget_tokens=400)
# ChatOpenAI(model=settings.model_name, ...)
```

Setting `SUMMARIZATION_MODEL_NAME=<router-endpoint>` in the environment is the only change needed to activate the router.

**`MAX_CONCURRENT` concurrency cap:**
Limits the number of concurrent LLM calls via `asyncio.Semaphore` in `ChunkSummarizer` (TASK-US017-04), preventing upstream rate-limit errors when many chunks require summarisation in a single request.

## Acceptance Criteria

- [ ] `SummarizationSettings()` loads `token_threshold=500`, `model_name="gpt-4o-mini"`, `target_ratio=0.40`
- [ ] `SUMMARIZATION_TOKEN_THRESHOLD=300` env var overrides the default to `300`
- [ ] `SUMMARIZATION_MODEL_NAME=gpt-4o` env var overrides the model
- [ ] `token_threshold=0` raises `ValidationError` (`ge=1`)
- [ ] `target_ratio=1.0` raises `ValidationError` (`lt=1.0`)
- [ ] `get_summarization_settings()` returns the same instance on repeated calls (singleton)

## Dependencies

- TASK-US016-01 (`SemanticDedupSettings` singleton pattern — consistent factory approach)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All constants documented in `docs/config/environment-variables.md`
- [ ] Unit tests cover: default load, env overrides, boundary validation, singleton
- [ ] `mypy --strict` passes; no `ruff` lint errors
