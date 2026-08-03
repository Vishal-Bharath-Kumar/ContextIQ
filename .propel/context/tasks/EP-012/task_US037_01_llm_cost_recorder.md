# TASK-US037-01 — `LLMCostRecorder`, `LLMCallRecord` Schema, and Langfuse Project Configuration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US037-01 |
| User Story | US-037 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the `LLMCallRecord` Pydantic schema that captures the six required fields per LLM invocation (AC-1), implement `LLMCostRecorder` which writes each record to Langfuse as a `Generation` event (AC-1, AC-4), and document the Langfuse project retention configuration required for the 12-month minimum (AC-5). `LLMCostRecorder` is called from `llm_metrics_node` (TASK-US037-03) as a fire-and-forget coroutine so it adds zero latency to the main request path.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2 (`ConfigDict(frozen=True)`), Langfuse `>=2.0` (`langfuse.create_generation()`), `pydantic-settings`

**File locations:**
- `src/observability/cost/schemas.py` — `LLMCallRecord`, `CompressionRecord`
- `src/observability/cost/recorder.py` — `LLMCostRecorder`
- `src/observability/cost/settings.py` — `LangfuseProjectSettings`

---

### `LLMCallRecord`

```python
# src/observability/cost/schemas.py
from __future__ import annotations
from datetime   import datetime
from uuid       import UUID

from pydantic import BaseModel, ConfigDict, Field


class LLMCallRecord(BaseModel):
    """
    Single LLM invocation record written to Langfuse (AC-1).

    Required fields per AC-1:
      model_id, prompt_tokens, completion_tokens, cost_usd, user_id, team_id
    """
    model_config = ConfigDict(frozen=True)

    # Identity
    request_id:        UUID
    tenant_id:         str

    # AC-1 required fields
    model_id:          str   = Field(description="LiteLLM model string, e.g. 'gpt-4o'.")
    prompt_tokens:     int   = Field(ge=0)
    completion_tokens: int   = Field(ge=0)
    cost_usd:          float = Field(ge=0.0, description="Cost in USD computed by LiteLLM cost map.")
    user_id:           str   = Field(description="JWT sub claim.")
    team_id:           str   = Field(description="Team extracted from JWT claims or default group.")

    # Supplementary fields for Grafana grouping (AC-3, AC-6)
    intent_type:       str   = "unknown"
    timestamp:         datetime


class CompressionRecord(BaseModel):
    """
    Compression savings record written to Langfuse (AC-2).
    Also used to populate Prometheus compression metrics (TASK-US037-02).
    """
    model_config = ConfigDict(frozen=True)

    request_id:                UUID
    tenant_id:                 str
    user_id:                   str
    team_id:                   str
    intent_type:               str = "unknown"
    timestamp:                 datetime

    # AC-2 required fields
    tokens_before_compression: int = Field(ge=0)
    tokens_after_compression:  int = Field(ge=0)

    # Derived — computed at write time, not stored separately
    @property
    def savings_tokens(self) -> int:
        return max(0, self.tokens_before_compression - self.tokens_after_compression)

    @property
    def savings_pct(self) -> float:
        if self.tokens_before_compression == 0:
            return 0.0
        return round(
            100 * self.savings_tokens / self.tokens_before_compression, 2
        )
```

---

### `LangfuseProjectSettings`

```python
# src/observability/cost/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class LangfuseProjectSettings(BaseSettings):
    """
    Langfuse project-level configuration.
    Retention (AC-5) is set at project creation time in the Langfuse admin UI
    or via the management API — not via the Python SDK.
    This settings object documents the required configuration for operators.
    """
    model_config = SettingsConfigDict(
        env_prefix = "LANGFUSE_",
        env_file   = ".env",
    )

    public_key:    str = ""
    secret_key:    str = ""
    host:          str = "https://cloud.langfuse.com"

    # AC-5: Langfuse project data retention must be set to >= 12 months
    # in the Langfuse project settings (Settings → Data Retention).
    # This constant is used in the startup health check to warn if unset.
    required_retention_months: int = 12
```

---

### `LLMCostRecorder`

```python
# src/observability/cost/recorder.py
from __future__ import annotations
import logging
from datetime import timezone

from langfuse import Langfuse

from src.observability.cost.schemas   import LLMCallRecord, CompressionRecord
from src.observability.cost.settings  import LangfuseProjectSettings

logger = logging.getLogger(__name__)


class LLMCostRecorder:
    """
    Writes LLM call records and compression records to Langfuse (AC-1, AC-2, AC-4).

    Langfuse stores each record as a Generation / Event with all six AC-1 fields
    as metadata, making them queryable via the Langfuse API and dashboard (AC-4).

    Write pattern: fire-and-forget — both methods are synchronous wrappers
    around the Langfuse SDK's non-blocking flush queue. They do not await IO
    and add no latency to the main request path.
    """

    def __init__(self, settings: LangfuseProjectSettings | None = None) -> None:
        cfg = settings or LangfuseProjectSettings()
        self._langfuse = Langfuse(
            public_key = cfg.public_key,
            secret_key = cfg.secret_key,
            host       = cfg.host,
        )

    def record_llm_call(self, record: LLMCallRecord) -> None:
        """
        AC-1: Write one LLM invocation to Langfuse as a Generation.
        All six AC-1 fields are included in `metadata` for Langfuse API
        queryability (AC-4).
        """
        try:
            self._langfuse.generation(
                id          = str(record.request_id),
                name        = f"llm-call/{record.model_id}",
                model       = record.model_id,
                usage       = {
                    "promptTokens":     record.prompt_tokens,
                    "completionTokens": record.completion_tokens,
                    "totalCost":        record.cost_usd,
                },
                metadata    = {
                    # AC-1 required fields
                    "model_id":          record.model_id,
                    "prompt_tokens":     record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                    "cost_usd":          record.cost_usd,
                    "user_id":           record.user_id,
                    "team_id":           record.team_id,
                    # Supplementary
                    "tenant_id":         record.tenant_id,
                    "intent_type":       record.intent_type,
                },
                start_time  = record.timestamp,
            )
        except Exception:
            logger.exception(
                "langfuse.record_llm_call failed request_id=%s", record.request_id
            )

    def record_compression(self, record: CompressionRecord) -> None:
        """
        AC-2: Write compression savings to Langfuse as a named event.
        """
        try:
            self._langfuse.event(
                name     = "compression_savings",
                metadata = {
                    "request_id":                 str(record.request_id),
                    "user_id":                    record.user_id,
                    "team_id":                    record.team_id,
                    "tenant_id":                  record.tenant_id,
                    "intent_type":                record.intent_type,
                    # AC-2 required fields
                    "tokens_before_compression":  record.tokens_before_compression,
                    "tokens_after_compression":   record.tokens_after_compression,
                    # Derived
                    "savings_tokens":             record.savings_tokens,
                    "savings_pct":                record.savings_pct,
                },
                start_time = record.timestamp,
            )
        except Exception:
            logger.exception(
                "langfuse.record_compression failed request_id=%s", record.request_id
            )

    def flush(self) -> None:
        """
        Flush the Langfuse SDK's internal queue.
        Called during lifespan shutdown to avoid losing buffered events.
        """
        self._langfuse.flush()
```

---

### Langfuse project retention (AC-5)

AC-5 requires a **minimum 12-month** data retention for cost records. Langfuse retention is configured at the project level — it is not a runtime SDK setting:

1. In Langfuse Cloud: `Project Settings → Data Retention → Set to 365+ days`
2. In self-hosted Langfuse: set `LANGFUSE_RETENTION_DAYS=365` in the Langfuse deployment env

Add a startup validation that warns if the Langfuse project retention cannot be confirmed:

```python
# src/main.py lifespan (add to existing startup checks)
from src.observability.cost.settings import LangfuseProjectSettings

settings = LangfuseProjectSettings()
logger.info(
    "Langfuse cost recording enabled. "
    "Ensure project data retention >= %d months (AC-5).",
    settings.required_retention_months,
)
```

## Acceptance Criteria

- [ ] `LLMCallRecord` contains all six AC-1 fields: `model_id`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `user_id`, `team_id`
- [ ] `LLMCostRecorder.record_llm_call()` calls `langfuse.generation()` with all six fields in `metadata`
- [ ] `LLMCostRecorder.record_compression()` calls `langfuse.event()` with `tokens_before_compression` and `tokens_after_compression` (AC-2)
- [ ] Both recorder methods silently log on exception — they never raise (fire-and-forget safety)
- [ ] `CompressionRecord.savings_pct` returns `0.0` when `tokens_before_compression == 0` (no division by zero)
- [ ] `LLMCostRecorder.flush()` is called in the application lifespan shutdown handler

## Dependencies

- Langfuse `>=2.0` (already in project)
- `pydantic-settings` (already in project)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
