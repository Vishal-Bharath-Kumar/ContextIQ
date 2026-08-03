"""ModelRouter: selection logic and intent-to-capability mapping (TASK-US019-03).

Provides:
- ``INTENT_CAPABILITY_MAP`` — maps each IntentType to the minimum required
  ModelCapability, used to filter ineligible candidates before scoring.
- ``ModelRouter`` — single entry-point for model selection; serves from
  ScoredModelCache on the hot path (< 50 ms) and falls back to a full
  score + populate cycle on cache miss.
"""

from __future__ import annotations

from src.agents.schemas.intent import IntentType
from src.model_invoker.config import InvokerSettings
from src.model_invoker.schemas.fallback_chain import FallbackChain
from src.model_registry.cache.model_cache import ModelListCache
from src.model_registry.schemas.model_definition import ModelCapability
from src.model_router.cache.scored_model_cache import ScoredModelCache
from src.model_router.schemas.model_score import ModelScore
from src.model_router.schemas.routing_weights import (
    INTENT_ROUTING_WEIGHT_TABLE,
    RoutingWeights,
)
from src.model_router.scoring import compute_model_score
from src.observability.langfuse_integration import observe_llm, update_current_observation

# ---------------------------------------------------------------------------
# Intent → required capability mapping
# ---------------------------------------------------------------------------

INTENT_CAPABILITY_MAP: dict[str, ModelCapability] = {
    IntentType.CODE_GEN: ModelCapability.CODE,
    IntentType.CODE_REVIEW: ModelCapability.CODE,
    IntentType.ARCHITECTURE: ModelCapability.CHAT,
    IntentType.DOCS: ModelCapability.CHAT,
    IntentType.INCIDENT: ModelCapability.CHAT,
    IntentType.METRICS: ModelCapability.CHAT,
    IntentType.DEBUGGING: ModelCapability.CODE,
    IntentType.GENERAL: ModelCapability.CHAT,
}


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Single entry-point for model selection.

    Serves scored results from ``ScoredModelCache`` on the hot path and
    falls back to scoring + cache population on a miss.
    """

    def __init__(
        self,
        model_list_cache: ModelListCache,
        scored_model_cache: ScoredModelCache,
    ) -> None:
        self._model_list_cache = model_list_cache
        self._scored_model_cache = scored_model_cache

    @observe_llm(as_type="span", name="model-router-select")
    async def select(
        self,
        intent_type: str,
        weights: RoutingWeights | None = None,
        cache_key: str | None = None,
    ) -> ModelScore | None:
        """Return the highest-scoring ModelScore for the given intent.

        Returns ``None`` if no eligible active model exists.
        """
        effective_weights = weights or INTENT_ROUTING_WEIGHT_TABLE.get(
            intent_type, INTENT_ROUTING_WEIGHT_TABLE[IntentType.GENERAL]
        )
        required_capability = INTENT_CAPABILITY_MAP.get(intent_type, ModelCapability.CHAT)
        routing_cache_key = cache_key or intent_type

        # Add metadata for observability
        update_current_observation(
            input={
                "intent_type": intent_type,
                "required_capability": required_capability.value,
            },
            metadata={
                "weights": {
                    "quality": effective_weights.quality_weight,
                    "cost": effective_weights.cost_weight,
                    "latency": effective_weights.latency_weight,
                }
            }
        )

        # Hot path — serve from pre-scored cache
        cached = await self._scored_model_cache.get(routing_cache_key)
        if cached:
            selected = cached[0]
            update_current_observation(
                output={
                    "model_id": selected.model_id,
                    "composite_score": selected.composite_score,
                    "source": "cache",
                },
                metadata={"cache_hit": True}
            )
            return selected  # list is sorted desc by composite_score

        # Cold path — score + populate cache
        candidates = await self._model_list_cache.get()
        if candidates is None:
            update_current_observation(
                output=None,
                metadata={"error": "model_list_cache_empty"}
            )
            return None  # model list cache is empty; ModelRouter cannot proceed

        eligible = [m for m in candidates if required_capability in m.capabilities]
        if not eligible:
            update_current_observation(
                output=None,
                metadata={"error": "no_eligible_models", "cache_hit": False}
            )
            return None

        scores = sorted(
            [compute_model_score(m, effective_weights) for m in eligible],
            key=lambda s: s.composite_score,
            reverse=True,
        )
        await self._scored_model_cache.set(routing_cache_key, scores)
        
        selected = scores[0]
        update_current_observation(
            output={
                "model_id": selected.model_id,
                "composite_score": selected.composite_score,
                "source": "computed",
            },
            metadata={
                "cache_hit": False,
                "eligible_models_count": len(eligible),
                "scored_models_count": len(scores),
            }
        )
        return selected

    async def build_fallback_chain(
        self,
        intent_type: str,
        settings: InvokerSettings | None = None,
        cache_key: str | None = None,
    ) -> FallbackChain | None:
        """Return an ordered FallbackChain of up to fallback_chain_size model IDs.

        Returns ``None`` if the scored candidate list is empty.
        """
        n = (settings or InvokerSettings()).fallback_chain_size
        routing_cache_key = cache_key or intent_type

        # Reuse existing scoring/cache logic — read full scored list, not just [0]
        cached = await self._scored_model_cache.get(routing_cache_key)
        if cached is None:
            # Cold path — populate cache via select(), then re-read
            await self.select(intent_type=intent_type, cache_key=routing_cache_key)
            cached = await self._scored_model_cache.get(routing_cache_key)

        if not cached:
            return None

        return FallbackChain(
            model_ids=[s.model_id for s in cached[:n]],
            intent_type=intent_type,
        )
