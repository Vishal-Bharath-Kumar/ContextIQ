"""Register default AI models in the model registry.

This script populates the model_registry table with commonly used models
to enable the Dynamic Model Router functionality.

Usage:
    docker compose exec api python -m scripts.registry.register_default_models
"""
import asyncio
import sys

sys.path.insert(0, "/app")
from sqlalchemy import select

from src.data.database import primary_session_factory
from src.model_registry.models.model import ModelRecord
from src.model_registry.schemas.model_definition import LatencyTier


async def register_default_models() -> None:
    """Register a default set of AI models using ORM."""
    async with primary_session_factory()() as session:
        # Check if models already exist
        result = await session.execute(select(ModelRecord))
        existing = result.scalars().all()
        
        if existing:
            print(f"⚠️  {len(existing)} models already registered:")
            for m in existing:
                print(f"   - {m.model_id} ({m.provider})")
            return

        models = [
            ModelRecord(
                model_id="gpt-4o-mini",
                provider="openai",
                context_window=128000,
                cost_per_1k_tokens=0.00015,
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "code", "function_call", "vision"],
                is_active=True,
            ),
            ModelRecord(
                model_id="gpt-4o",
                provider="openai",
                context_window=128000,
                cost_per_1k_tokens=0.0025,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "completion", "code", "function_call", "vision", "summarization"],
                is_active=True,
            ),
            ModelRecord(
                model_id="claude-3-haiku-20240307",
                provider="anthropic",
                context_window=200000,
                cost_per_1k_tokens=0.00025,
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "code", "summarization"],
                is_active=True,
            ),
            ModelRecord(
                model_id="claude-3-5-sonnet-20241022",
                provider="anthropic",
                context_window=200000,
                cost_per_1k_tokens=0.003,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "completion", "code", "function_call", "vision", "summarization"],
                is_active=True,
            ),
            ModelRecord(
                model_id="deepseek-coder",
                provider="deepseek",
                context_window=16000,
                cost_per_1k_tokens=0.00014,
                latency_tier=LatencyTier.FAST,
                capabilities=["code", "completion"],
                is_active=True,
            ),
            ModelRecord(
                model_id="llama-3.1-70b",
                provider="meta",
                context_window=128000,
                cost_per_1k_tokens=0.0006,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "completion", "code", "summarization"],
                is_active=True,
            ),
            ModelRecord(
                model_id="mistral-large-latest",
                provider="mistral",
                context_window=128000,
                cost_per_1k_tokens=0.002,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "completion", "code", "function_call"],
                is_active=True,
            ),
        ]

        for model in models:
            session.add(model)
            print(f"✓ Registering: {model.model_id:35s} ({model.provider})")

        await session.commit()
        print(f"\n✅ Successfully registered {len(models)} models")


if __name__ == "__main__":
    asyncio.run(register_default_models())


if __name__ == "__main__":
    asyncio.run(register_default_models())
