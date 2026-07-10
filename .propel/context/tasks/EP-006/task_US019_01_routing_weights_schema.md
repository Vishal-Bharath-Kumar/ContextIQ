# TASK-US019-01 — `RoutingWeights` Schema, Intent Weight Table, and `AgentState` Extensions

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US019-01 |
| User Story | US-019 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the frozen `RoutingWeights` Pydantic model, populate `INTENT_ROUTING_WEIGHT_TABLE` with per-intent presets, implement `RoutingSettings` for environment-variable overrides, and extend `AgentState` with the two new routing output fields required by downstream nodes.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/model_router/schemas/routing_weights.py` — `RoutingWeights` + `INTENT_ROUTING_WEIGHT_TABLE`
- `src/model_router/config.py` — `RoutingSettings`
- `src/agents/state.py` — `AgentState` extensions (patch only)
- `tests/model_router/test_routing_weights.py`

**`RoutingWeights`:**

```python
# src/model_router/schemas/routing_weights.py
from pydantic import BaseModel, ConfigDict, model_validator

class RoutingWeights(BaseModel):
    model_config = ConfigDict(frozen=True)

    quality_weight: float   # 0.0 – 1.0
    cost_weight:    float   # 0.0 – 1.0
    latency_weight: float   # 0.0 – 1.0

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "RoutingWeights":
        total = round(self.quality_weight + self.cost_weight + self.latency_weight, 6)
        if total != 1.0:
            raise ValueError(f"Routing weights must sum to 1.0, got {total}")
        return self
```

**`INTENT_ROUTING_WEIGHT_TABLE`:**

Maps each of the 8 intent types (mirroring `SOURCE_MAP` in TASK-US009-03) to a `RoutingWeights` preset. Intent semantics drive weight priorities:

| Intent | quality | cost | latency | Rationale |
|---|---|---|---|---|
| `code_generation` | 0.70 | 0.20 | 0.10 | Correctness critical; cost secondary |
| `code_review` | 0.65 | 0.25 | 0.10 | Nuanced analysis; cost moderate |
| `summarization` | 0.30 | 0.50 | 0.20 | Cost-first; good-enough quality OK |
| `documentation` | 0.40 | 0.40 | 0.20 | Balanced |
| `question_answering` | 0.50 | 0.30 | 0.20 | Quality matters for factual accuracy |
| `debugging` | 0.65 | 0.25 | 0.10 | Reasoning-heavy; cost secondary |
| `refactoring` | 0.60 | 0.30 | 0.10 | Code quality; cost moderate |
| `general` | 0.40 | 0.40 | 0.20 | Balanced fallback |

```python
from src.intents.constants import IntentType   # 8-value StrEnum from EP-003

INTENT_ROUTING_WEIGHT_TABLE: dict[str, RoutingWeights] = {
    IntentType.CODE_GENERATION:  RoutingWeights(quality_weight=0.70, cost_weight=0.20, latency_weight=0.10),
    IntentType.CODE_REVIEW:      RoutingWeights(quality_weight=0.65, cost_weight=0.25, latency_weight=0.10),
    IntentType.SUMMARIZATION:    RoutingWeights(quality_weight=0.30, cost_weight=0.50, latency_weight=0.20),
    IntentType.DOCUMENTATION:    RoutingWeights(quality_weight=0.40, cost_weight=0.40, latency_weight=0.20),
    IntentType.QUESTION_ANSWERING: RoutingWeights(quality_weight=0.50, cost_weight=0.30, latency_weight=0.20),
    IntentType.DEBUGGING:        RoutingWeights(quality_weight=0.65, cost_weight=0.25, latency_weight=0.10),
    IntentType.REFACTORING:      RoutingWeights(quality_weight=0.60, cost_weight=0.30, latency_weight=0.10),
    IntentType.GENERAL:          RoutingWeights(quality_weight=0.40, cost_weight=0.40, latency_weight=0.20),
}
```

**`RoutingSettings`:**

```python
# src/model_router/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class RoutingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROUTING_", env_file=".env", extra="ignore")

    # Per-intent weight overrides (JSON-encoded RoutingWeights)
    weights_code_generation:   str | None = None
    weights_summarization:     str | None = None
    weights_code_review:       str | None = None
    weights_documentation:     str | None = None
    weights_question_answering: str | None = None
    weights_debugging:         str | None = None
    weights_refactoring:       str | None = None
    weights_general:           str | None = None
```

Override resolution: if `ROUTING_WEIGHTS_CODE_GENERATION` is set, parse it as `RoutingWeights` and replace the table entry at startup. The table is built once at module import and treated as immutable thereafter.

**`AgentState` extensions:**

```python
# src/agents/state.py  — patch only; do not alter existing fields
class AgentState(TypedDict, total=False):
    ...                             # existing fields unchanged
    selected_model_id: str | None   # e.g. "gpt-4o-mini"
    routing_score:     float | None # composite score of selected model (0.0–1.0)
```

## Acceptance Criteria

- [ ] `RoutingWeights(quality_weight=0.7, cost_weight=0.2, latency_weight=0.1)` constructs successfully
- [ ] `RoutingWeights(quality_weight=0.5, cost_weight=0.5, latency_weight=0.1)` raises `ValidationError` (sum = 1.1)
- [ ] `INTENT_ROUTING_WEIGHT_TABLE` has exactly 8 entries — one per `IntentType`
- [ ] All 8 presets pass the `weights_sum_to_one` validator
- [ ] `RoutingSettings` loads from environment; `ROUTING_WEIGHTS_CODE_GENERATION` overrides table entry
- [ ] `AgentState` fields `selected_model_id` and `routing_score` exist; both default to `None`

## Dependencies

- US-009 / TASK-US009-03 (`IntentType` StrEnum — intent type constants)
- TASK-US018-01 (`RoutingWeights` does not extend `ModelDefinition`; this is a new schema file)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All 8 preset entries validated by unit test
- [ ] `mypy --strict` passes; no `ruff` lint errors
