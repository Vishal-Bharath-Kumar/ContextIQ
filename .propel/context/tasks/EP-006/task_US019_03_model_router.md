# TASK-US019-03 — `ModelRouter`: Selection Logic and Intent-to-Capability Mapping

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US019-03 |
| User Story | US-019 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ModelRouter`, the single entry-point for model selection. It reads from `ScoredModelCache` on a hot path (< 50 ms) and falls back to a full score + populate cycle on cache miss. An `INTENT_CAPABILITY_MAP` translates each of the 8 intent types to the required `ModelCapability`, filtering out models that cannot satisfy the request before scoring.

## Implementation Details

**Technology:** Python 3.11+, `redis.asyncio`

**File locations:**
- `src/model_router/router.py` — `ModelRouter`, `INTENT_CAPABILITY_MAP`
- `tests/model_router/test_model_router.py`

**`INTENT_CAPABILITY_MAP`:**

Maps each intent type to the `ModelCapability` that a candidate model must declare. If no capability filter is needed for an intent (e.g. `general`), the map returns `ModelCapability.CHAT` as the minimum requirement.

```python
# src/model_router/router.py
from src.intents.constants import IntentType
from src.model_registry.schemas.model_definition import ModelCapability

INTENT_CAPABILITY_MAP: dict[str, ModelCapability] = {
    IntentType.CODE_GENERATION:   ModelCapability.CODE,
    IntentType.CODE_REVIEW:       ModelCapability.CODE,
    IntentType.REFACTORING:       ModelCapability.CODE,
    IntentType.SUMMARIZATION:     ModelCapability.SUMMARIZATION,
    IntentType.DOCUMENTATION:     ModelCapability.CHAT,
    IntentType.QUESTION_ANSWERING: ModelCapability.CHAT,
    IntentType.DEBUGGING:         ModelCapability.CODE,
    IntentType.GENERAL:           ModelCapability.CHAT,
}
```

**`ModelRouter`:**

```python
# src/model_router/router.py
import asyncio
from src.model_registry.schemas.model_definition import ModelDefinition, ModelCapability
from src.model_registry.cache.model_cache         import ModelListCache
from src.model_router.cache.scored_model_cache     import ScoredModelCache
from src.model_router.schemas.model_score          import ModelScore
from src.model_router.schemas.routing_weights      import RoutingWeights, INTENT_ROUTING_WEIGHT_TABLE
from src.model_router.scoring                      import compute_model_score

class ModelRouter:
    def __init__(
        self,
        model_list_cache:   ModelListCache,
        scored_model_cache: ScoredModelCache,
    ) -> None:
        self._model_list_cache   = model_list_cache
        self._scored_model_cache = scored_model_cache

    async def select(
        self,
        intent_type: str,
        weights:     RoutingWeights | None = None,
    ) -> ModelScore | None:
        """
        Return the highest-scoring ModelScore for the given intent.
        Returns None if no eligible active model exists.
        """
        effective_weights = weights or INTENT_ROUTING_WEIGHT_TABLE.get(
            intent_type, INTENT_ROUTING_WEIGHT_TABLE["general"]
        )
        required_capability = INTENT_CAPABILITY_MAP.get(intent_type, ModelCapability.CHAT)

        # Hot path — serve from pre-scored cache
        cached = await self._scored_model_cache.get(intent_type)
        if cached:
            return cached[0]   # list is sorted desc by composite_score

        # Cold path — score + populate cache
        candidates = await self._model_list_cache.get()
        if candidates is None:
            return None   # model list cache is empty; ModelRouter cannot proceed

        eligible = [
            m for m in candidates
            if required_capability in m.capabilities
        ]
        if not eligible:
            return None

        scores = sorted(
            [compute_model_score(m, effective_weights) for m in eligible],
            key=lambda s: s.composite_score,
            reverse=True,
        )
        await self._scored_model_cache.set(intent_type, scores)
        return scores[0]
```

**`ModelListCache` warm-up guarantee:**

`ModelRouter.select()` treats an empty `ModelListCache` as a non-fatal miss and returns `None`. The caller (`routing_node()` in TASK-US019-04) must handle `None` — typically by falling back to a hardcoded default model ID defined in `RoutingSettings.fallback_model_id`.

**Routing latency SLA (< 50 ms — US-019 AC-5):**

On the hot path (`ScoredModelCache` hit), the only I/O is a single Redis `GET`. In CI benchmark tests, target P99 < 10 ms for the `ScoredModelCache.get()` call. The 50 ms budget covers the full `routing_node()` including OTel span creation (TASK-US019-04).

**Capability filter behaviour:**

`required_capability in m.capabilities` uses the `ModelCapability` JSONB array from `ModelDefinition.capabilities`. The filter is applied before scoring so that ineligible models never enter the ranked list.

## Acceptance Criteria

- [ ] `select()` returns the model with the highest `composite_score` from the candidate list
- [ ] `select()` filters out models that do not declare the required `ModelCapability`
- [ ] `select()` returns `None` when no eligible model exists (empty `ModelListCache` or empty filtered list)
- [ ] On cache miss, `select()` populates `ScoredModelCache` before returning
- [ ] On cache hit, `select()` does NOT call `ModelListCache.get()` (mock call count verified)
- [ ] `INTENT_CAPABILITY_MAP` covers all 8 intent types

## Dependencies

- TASK-US019-01 (`INTENT_ROUTING_WEIGHT_TABLE`, `RoutingWeights`)
- TASK-US019-02 (`ModelScore`, `ScoredModelCache`, `compute_model_score()`)
- TASK-US018-01 (`ModelDefinition`, `ModelCapability`)
- TASK-US018-05 (`ModelListCache`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests: cache-hit path (mock `scored_model_cache.get` returns list), cache-miss path (mock `model_list_cache.get`), empty candidates → `None`, capability filter, weight override
- [ ] `mypy --strict` passes; no `ruff` lint errors
