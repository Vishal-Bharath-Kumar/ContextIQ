# TASK-US018-01 — `ModelDefinition` Schema, `LatencyTier`, and `ModelCapability` Enums

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US018-01 |
| User Story | US-018 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the canonical Pydantic types for the Model Capability Registry: `LatencyTier`, `ModelCapability`, `ModelRegistration` (inbound API payload), and `ModelDefinition` (the stored + returned representation). These types are the contract shared by the API endpoints (TASK-US018-04), the service layer (TASK-US018-03), the Redis cache (TASK-US018-05), and the Dynamic Model Router (US-019).

## Implementation Details

**Technology:** Python 3.11+, `pydantic>=2.0`

**File locations:**
- `src/model_registry/schemas/model_definition.py` — all types
- `tests/model_registry/schemas/test_model_definition.py`

**Enums:**

```python
# src/model_registry/schemas/model_definition.py
from enum import StrEnum

class LatencyTier(StrEnum):
    FAST    = "fast"     # p95 < 500 ms (e.g. gpt-4o-mini, claude-haiku)
    MEDIUM  = "medium"   # p95 500 ms – 2 s (e.g. gpt-4o)
    SLOW    = "slow"     # p95 > 2 s (e.g. o1, deep-reasoning models)

class ModelCapability(StrEnum):
    CHAT          = "chat"          # conversational turn completion
    COMPLETION    = "completion"    # single-turn text generation
    EMBEDDING     = "embedding"     # vector embedding output
    CODE          = "code"          # code-optimised generation
    SUMMARIZATION = "summarization" # long-text compression
    VISION        = "vision"        # image + text input
    FUNCTION_CALL = "function_call" # tool/function calling support
```

**`ModelRegistration` — inbound API payload:**

```python
from pydantic import BaseModel, Field
from uuid import UUID

class ModelRegistration(BaseModel):
    model_id:           str               = Field(
        min_length=1, max_length=128,
        description="Unique identifier, e.g. 'gpt-4o-mini' or 'anthropic/claude-3-haiku'",
    )
    provider:           str               = Field(min_length=1, max_length=64)
    context_window:     int               = Field(gt=0, description="Max tokens in context window")
    cost_per_1k_tokens: float             = Field(ge=0.0, description="USD per 1 000 tokens (combined input+output average)")
    latency_tier:       LatencyTier
    capabilities:       list[ModelCapability] = Field(min_length=1)
    is_active:          bool              = True
```

**`ModelDefinition` — stored + returned representation:**

```python
from datetime import datetime

class ModelDefinition(ModelRegistration):
    id:         UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)   # SQLAlchemy ORM → Pydantic
```

**Validation notes:**
- `capabilities` must contain at least one entry — an uncategorised model cannot be routed
- `cost_per_1k_tokens = 0.0` is valid (open-source self-hosted models have zero marginal cost)
- `model_id` must be URL-safe to serve as a Redis key segment — enforce `r'^[a-zA-Z0-9._\-/]+$'` via `field_validator`

```python
import re
from pydantic import field_validator

@field_validator("model_id")
@classmethod
def model_id_url_safe(cls, v: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9._\-/]+", v):
        raise ValueError("model_id must contain only alphanumeric, '.', '_', '-', '/' characters")
    return v
```

## Acceptance Criteria

- [ ] `ModelRegistration` with all required fields validates successfully
- [ ] `capabilities=[]` raises `ValidationError` (`min_length=1`)
- [ ] `model_id="gpt 4o mini"` (space) raises `ValidationError` (URL-safe guard)
- [ ] `model_id="anthropic/claude-3-haiku"` (slash) passes validation
- [ ] `cost_per_1k_tokens=0.0` is valid
- [ ] `ModelDefinition.model_config = ConfigDict(from_attributes=True)` — ORM-to-Pydantic coercion works

## Dependencies

- None (foundation type; all other US-018 tasks depend on this)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `ModelDefinition` is the single canonical model type — no raw `dict` shapes used in registry code
- [ ] Unit tests cover: valid payload, empty capabilities, invalid model_id characters, ORM coercion
- [ ] `mypy --strict` passes; no `ruff` lint errors
