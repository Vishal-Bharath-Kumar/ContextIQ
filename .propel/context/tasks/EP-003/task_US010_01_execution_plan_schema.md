# TASK-US010-01 — Define `ExecutionPlan` Pydantic Schema and Upgrade `AgentState` Type

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US010-01 |
| User Story | US-010 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define the canonical `ExecutionPlan` Pydantic model that is stored in `AgentState`. This replaces the untyped `Optional[dict]` placeholder in `AgentState.execution_plan` (TASK-US005-01) with a strongly-typed model, enforcing the four required plan fields at construction time and enabling type-safe access throughout the pipeline.

## Implementation Details

**Technology:** Python 3.11+, `pydantic>=2.0`, `langgraph>=0.2.0`

**File locations:**
- `src/agents/schemas/execution_plan.py` — `ExecutionPlan` model and `RankingStrategy` enum
- `src/agents/state.py` — `AgentState.execution_plan` type annotation update
- `tests/agents/schemas/test_execution_plan.py`

**`RankingStrategy` enum:**

```python
# src/agents/schemas/execution_plan.py
from enum import StrEnum
from pydantic import BaseModel, Field

class RankingStrategy(StrEnum):
    SEMANTIC = "semantic"    # dense vector similarity (default for code-gen, docs, architecture)
    BM25     = "bm25"        # keyword/lexical (metrics, incident — exact metric names matter)
    HYBRID   = "hybrid"      # weighted blend (general, debugging, code-review)
```

**`ExecutionPlan` model:**

```python
class ExecutionPlan(BaseModel):
    sources:               list[str]        # ordered connector IDs to query (from AIR-006 mapping)
    token_budget_total:    int = Field(default=8_000, ge=1_000, le=32_000)
    token_budget_per_source: dict[str, int] # source_id → allocated token quota
    ranking_strategy:      RankingStrategy  # retrieval ranking algorithm
    cache_eligible:        bool             # whether plan result may be served from Redis cache

    model_config = ConfigDict(frozen=True)  # immutable once generated
```

**`AgentState` update (`src/agents/state.py`):**

```python
# Replace the existing Optional[dict] annotation — do NOT redefine other fields
from src.agents.schemas.execution_plan import ExecutionPlan

class AgentState(TypedDict, total=False):
    # ... existing fields unchanged ...

    # EP-003 / US-010 — typed plan replaces Optional[dict]
    execution_plan: Optional[ExecutionPlan]
```

**Serialisation contract:**
- `ExecutionPlan` must be JSON-serialisable via `model.model_dump()` for Kafka event payloads (TASK-US010-05) and LangGraph state checkpointing
- `model_config = ConfigDict(frozen=True)` prevents in-place mutation after the Intent Agent writes it

## Acceptance Criteria

- [ ] `ExecutionPlan` instantiation succeeds with all four required fields populated
- [ ] `token_budget_total < 1_000` raises `ValidationError`
- [ ] `token_budget_total > 32_000` raises `ValidationError`
- [ ] `ExecutionPlan.model_dump()` serialises to a JSON-compatible dict with no custom types
- [ ] `AgentState.execution_plan` is typed as `Optional[ExecutionPlan]` — `mypy --strict` confirms no `dict` annotation remains
- [ ] `model_config = ConfigDict(frozen=True)` — mutating a field post-construction raises `ValidationError`

## Dependencies

- TASK-US005-01 (`AgentState` TypedDict — `execution_plan: Optional[dict]` to be upgraded)
- TASK-US009-03 (`SOURCE_MAP` source key list — `sources` field must be a subset of those keys)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `ExecutionPlan` is the single canonical plan definition — no raw `dict` shapes used in pipeline code
- [ ] Unit tests cover: valid construction, field validation errors, `model_dump()` round-trip
- [ ] `mypy --strict` passes on `execution_plan.py` and `state.py`
- [ ] No `ruff` lint errors
