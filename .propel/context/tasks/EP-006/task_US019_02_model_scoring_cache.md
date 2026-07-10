# TASK-US019-02 — `ModelScore`, Scoring Function, and Pre-Scored Candidate Cache

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US019-02 |
| User Story | US-019 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend / Caching |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `ModelScore` output schema, the `compute_model_score()` pure function (weighted composite of quality, cost, and latency), and `ScoredModelCache` — a Redis cache keyed per intent type that holds a pre-scored, pre-sorted candidate list. The cache eliminates per-request scoring overhead and drives the < 50 ms routing latency SLA from US-019 AC-5.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `redis.asyncio`

**File locations:**
- `src/model_router/schemas/model_score.py` — `ModelScore`
- `src/model_router/scoring.py` — `compute_model_score()`, `LATENCY_TIER_SCORE`
- `src/model_router/cache/scored_model_cache.py` — `ScoredModelCache`
- `tests/model_router/test_scoring.py`
- `tests/model_router/cache/test_scored_model_cache.py`

**`ModelScore`:**

```python
# src/model_router/schemas/model_score.py
from pydantic import BaseModel, ConfigDict

class ModelScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id:          str
    quality_score:     float   # 0.0–1.0; derived from latency tier (proxy for capability quality)
    normalised_cost:   float   # 1 / cost_per_1k_tokens; 1.0 for zero-cost models
    normalised_latency: float  # 1 / latency_tier_ordinal; see LATENCY_TIER_SCORE
    composite_score:   float   # weighted sum
```

**`LATENCY_TIER_SCORE` and quality proxy:**

`LatencyTier` encodes observable latency and is used as a quality proxy — slower models (e.g. `o1`) indicate heavier reasoning. The mapping is:

```python
# src/model_router/scoring.py
from src.model_registry.schemas.model_definition import LatencyTier

# Ordinal: FAST=1, MEDIUM=2, SLOW=3 (higher ordinal → lower latency score)
LATENCY_TIER_ORDINAL: dict[LatencyTier, int] = {
    LatencyTier.FAST:   1,
    LatencyTier.MEDIUM: 2,
    LatencyTier.SLOW:   3,
}

# Quality proxy: SLOW models score highest on quality dimension
LATENCY_TIER_QUALITY: dict[LatencyTier, float] = {
    LatencyTier.FAST:   0.60,
    LatencyTier.MEDIUM: 0.80,
    LatencyTier.SLOW:   1.00,
}
```

**`compute_model_score()`:**

```python
from src.model_registry.schemas.model_definition import ModelDefinition
from src.model_router.schemas.routing_weights    import RoutingWeights
from src.model_router.schemas.model_score        import ModelScore

_COST_EPSILON = 1e-6   # prevent division by zero for zero-cost models

def compute_model_score(model: ModelDefinition, weights: RoutingWeights) -> ModelScore:
    quality_score      = LATENCY_TIER_QUALITY[model.latency_tier]
    normalised_cost    = 1.0 / (model.cost_per_1k_tokens + _COST_EPSILON)
    normalised_latency = 1.0 / LATENCY_TIER_ORDINAL[model.latency_tier]

    composite = (
        weights.quality_weight  * quality_score
        + weights.cost_weight   * normalised_cost
        + weights.latency_weight * normalised_latency
    )

    return ModelScore(
        model_id           = model.model_id,
        quality_score      = quality_score,
        normalised_cost    = normalised_cost,
        normalised_latency = normalised_latency,
        composite_score    = composite,
    )
```

Note: `normalised_cost` is unbounded (large for cheap models). The composite is used only for **relative ranking** within a candidate list — callers must not interpret the raw value as a probability.

**`ScoredModelCache`:**

Redis key: `contextiq:model_router:scored:{intent_type}`
TTL: 30 seconds (short — model list changes propagate from `ModelListCache` invalidation events)

```python
# src/model_router/cache/scored_model_cache.py
import json
from redis.asyncio import Redis
from src.model_router.schemas.model_score import ModelScore

class ScoredModelCache:
    KEY_PREFIX  = "contextiq:model_router:scored"
    TTL_SECONDS = 30

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, intent_type: str) -> str:
        return f"{self.KEY_PREFIX}:{intent_type}"

    async def get(self, intent_type: str) -> list[ModelScore] | None:
        raw = await self._redis.get(self._key(intent_type))
        if raw is None:
            return None
        return [ModelScore.model_validate(item) for item in json.loads(raw)]

    async def set(self, intent_type: str, scores: list[ModelScore]) -> None:
        payload = json.dumps([s.model_dump(mode="json") for s in scores])
        await self._redis.set(self._key(intent_type), payload, ex=self.TTL_SECONDS)

    async def invalidate(self, intent_type: str) -> None:
        await self._redis.delete(self._key(intent_type))

    async def invalidate_all(self) -> None:
        """Called when model list changes; uses SCAN to avoid blocking Redis."""
        pattern = f"{self.KEY_PREFIX}:*"
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self._redis.delete(*keys)
            if cursor == 0:
                break
```

**Cache population (on miss):**

The `ModelRouter` (TASK-US019-03) is responsible for populating the cache on a miss:
1. Load candidates from `ModelListCache` (TASK-US018-05)
2. Filter by required `ModelCapability`
3. Score each model via `compute_model_score(model, weights)`
4. Sort descending by `composite_score`
5. Write to `ScoredModelCache.set(intent_type, scored_list)`

## Acceptance Criteria

- [ ] `compute_model_score()` returns a `ModelScore` with `composite_score` equal to the manual weighted sum
- [ ] `compute_model_score()` handles `cost_per_1k_tokens = 0.0` without `ZeroDivisionError`
- [ ] Models with `LatencyTier.SLOW` score highest on `quality_score` (1.0)
- [ ] `ScoredModelCache.get()` returns `None` on cold cache
- [ ] `ScoredModelCache.set()` + `get()` round-trips a `list[ModelScore]` without data loss
- [ ] `ScoredModelCache.invalidate_all()` uses `SCAN` (not `KEYS`) — verified by inspecting Redis client call args
- [ ] TTL is 30 seconds — verified via `PTTL` assertion

## Dependencies

- TASK-US019-01 (`RoutingWeights` — passed into `compute_model_score()`)
- TASK-US018-01 (`ModelDefinition`, `LatencyTier`, `ModelCapability`)
- TASK-US018-05 (`ModelListCache` — upstream of cache population in `ModelRouter`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `fakeredis.aioredis`; no live Redis in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
