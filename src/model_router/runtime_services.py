from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.model_invoker.circuit_breaker import ProviderCircuitBreaker
from src.model_invoker.fallback_invoker import FallbackInvoker
from src.model_invoker.invoker import LiteLLMInvoker
from src.model_registry.cache.model_cache import ModelListCache
from src.model_registry.repositories.model_repository import ModelRepository
from src.model_registry.schemas.model_definition import ModelDefinition
from src.model_router.cache.scored_model_cache import ScoredModelCache
from src.model_router.repositories.routing_weight_repository import RoutingWeightRepository
from src.model_router.schemas.routing_weights import RoutingWeights


class RoutingRuntimeServices:
    """Runtime helpers for model routing and invocation.

    Owns the Redis-backed routing caches plus the read-through database access
    needed to resolve active models and per-intent weight overrides during a
    live pipeline execution.
    """

    def __init__(
        self,
        *,
        redis,
        session_factory: async_sessionmaker[AsyncSession],
        langfuse: object | None = None,
    ) -> None:
        self._redis = redis
        self._session_factory = session_factory
        self.langfuse = langfuse
        self.model_list_cache = ModelListCache(redis)
        self.scored_model_cache = ScoredModelCache(redis)
        self.invoker = LiteLLMInvoker()
        self.circuit_breaker = ProviderCircuitBreaker(redis)
        self.fallback_invoker = FallbackInvoker(
            invoker=self.invoker,
            circuit_breaker=self.circuit_breaker,
        )

    async def get_routing_weights(self, intent_type: str) -> RoutingWeights:
        async with self._session_factory() as session:
            repo = RoutingWeightRepository(session)
            return await repo.get(intent_type)

    async def get_active_models(self) -> list[ModelDefinition]:
        cached = await self.model_list_cache.get()
        if cached is not None:
            return cached

        async with self._session_factory() as session:
            repo = ModelRepository(session)
            records = await repo.list_active()

        models = [ModelDefinition.model_validate(record) for record in records]
        await self.model_list_cache.set(models)
        return models

    async def prime_model_list_cache(self) -> list[ModelDefinition]:
        return await self.get_active_models()

    async def get_model_definition(self, model_id: str) -> ModelDefinition | None:
        for model in await self.get_active_models():
            if model.model_id == model_id:
                return model
        return None

    async def invalidate_scored_routes(self) -> None:
        await self.scored_model_cache.invalidate_all()

    async def close(self) -> None:
        await self._redis.aclose()