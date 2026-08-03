"""Register Ollama models in the ContextIQ model registry.

This script replaces the paid API models with free local Ollama models:
- llama3.2 (3B, fast, general purpose)
- deepseek-coder:6.7b (code generation)
- phi3 (3.8B, reasoning)

All models run locally with $0 cost.
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from src.data.database import primary_session_factory
from src.model_registry.models.model import ModelRecord
from src.model_registry.schemas.model_definition import LatencyTier
from sqlalchemy import select, delete


async def clear_existing_models():
    """Clear existing models from the registry."""
    async with primary_session_factory()() as session:
        await session.execute(delete(ModelRecord))
        await session.commit()
        print("✓ Cleared existing models")


async def register_ollama_models():
    """Register Ollama models in the model registry."""
    async with primary_session_factory()() as session:
        # Check if models already exist
        result = await session.execute(select(ModelRecord))
        existing = result.scalars().all()
        
        if existing:
            print(f"Found {len(existing)} existing models. Clearing...")
            await clear_existing_models()

        # Define Ollama models
        # NOTE: LiteLLM expects "ollama/" prefix for Ollama models
        models = [
            ModelRecord(
                model_id="ollama/llama3.2",
                provider="ollama",
                context_window=128000,
                cost_per_1k_tokens=0.0,  # Free!
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "code", "summarization"],
                is_active=True,
            ),
            ModelRecord(
                model_id="ollama/deepseek-coder:6.7b",
                provider="ollama",
                context_window=16000,
                cost_per_1k_tokens=0.0,  # Free!
                latency_tier=LatencyTier.FAST,
                capabilities=["code", "completion"],
                is_active=True,
            ),
            ModelRecord(
                model_id="ollama/phi3",
                provider="ollama",
                context_window=128000,
                cost_per_1k_tokens=0.0,  # Free!
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "summarization"],
                is_active=True,
            ),
            # Add llama3.1 (8B) if you want a more powerful model
            ModelRecord(
                model_id="ollama/llama3.1",
                provider="ollama",
                context_window=128000,
                cost_per_1k_tokens=0.0,  # Free!
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "completion", "code", "summarization"],
                is_active=True,
            ),
        ]

        print("\nRegistering Ollama models...")
        for model in models:
            session.add(model)
            print(f"✓ {model.model_id:35s} | {model.provider:10s} | FREE | {model.latency_tier}")

        await session.commit()
        print(f"\n✅ Successfully registered {len(models)} Ollama models")
        print("\n💡 All models run locally - no API costs!")


async def verify_registration():
    """Verify the models were registered correctly."""
    async with primary_session_factory()() as session:
        result = await session.execute(
            select(ModelRecord).where(ModelRecord.provider == "ollama")
        )
        models = result.scalars().all()
        
        print("\n" + "=" * 80)
        print("REGISTERED OLLAMA MODELS")
        print("=" * 80)
        
        for m in models:
            caps = ", ".join(m.capabilities)
            print(f"✓ {m.model_id:35s} | {m.latency_tier:6s} | {caps}")
        
        print("\n" + "=" * 80)
        print(f"Total: {len(models)} models | Cost: $0.00")
        print("=" * 80)


if __name__ == "__main__":
    print("=" * 80)
    print("REGISTERING OLLAMA MODELS (FREE LOCAL INFERENCE)")
    print("=" * 80)
    
    asyncio.run(register_ollama_models())
    asyncio.run(verify_registration())
    
    print("\n✅ Registration complete!")
    print("\nNext steps:")
    print("1. Make sure Ollama is running: ollama serve")
    print("2. Test the integration: python scripts/registry/test_ollama_integration.py")
