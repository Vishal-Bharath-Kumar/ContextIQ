"""Register additional models for enhanced dynamic routing.

This script adds more model diversity to enable effective routing based on:
- Cost optimization (free Ollama → cheap → premium)
- Latency tiers (fast → medium → slow)
- Specialized capabilities (embedding, vision, function calling, code)

Usage:
    docker compose exec api python -m scripts.registry.register_additional_models
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from src.data.database import primary_session_factory
from src.model_registry.models.model import ModelRecord
from src.model_registry.schemas.model_definition import LatencyTier
from sqlalchemy import select


async def register_additional_models():
    """Register additional models for dynamic routing diversity."""
    async with primary_session_factory()() as session:
        # Check existing models
        result = await session.execute(select(ModelRecord))
        existing = result.scalars().all()
        existing_ids = {m.model_id for m in existing}
        
        print(f"📊 Found {len(existing)} existing models")
        
        # Define additional models for diverse routing
        new_models = [
            # ============ EMBEDDING MODELS ============
            ModelRecord(
                model_id="text-embedding-3-small",
                provider="openai",
                context_window=8191,
                cost_per_1k_tokens=0.00002,
                latency_tier=LatencyTier.FAST,
                capabilities=["embedding"],
                is_active=True,
            ),
            ModelRecord(
                model_id="text-embedding-3-large",
                provider="openai",
                context_window=8191,
                cost_per_1k_tokens=0.00013,
                latency_tier=LatencyTier.FAST,
                capabilities=["embedding"],
                is_active=True,
            ),
            ModelRecord(
                model_id="ollama/nomic-embed-text",
                provider="ollama",
                context_window=8192,
                cost_per_1k_tokens=0.0,
                latency_tier=LatencyTier.FAST,
                capabilities=["embedding"],
                is_active=True,
            ),
            
            # ============ FAST & CHEAP MODELS ============
            ModelRecord(
                model_id="gpt-3.5-turbo",
                provider="openai",
                context_window=16385,
                cost_per_1k_tokens=0.0005,
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "function_call"],
                is_active=True,
            ),
            ModelRecord(
                model_id="claude-3-opus-20240229",
                provider="anthropic",
                context_window=200000,
                cost_per_1k_tokens=0.015,
                latency_tier=LatencyTier.SLOW,
                capabilities=["chat", "completion", "code", "vision", "function_call", "summarization"],
                is_active=True,
            ),
            
            # ============ OLLAMA LOCAL MODELS ============
            ModelRecord(
                model_id="ollama/qwen2.5-coder:7b",
                provider="ollama",
                context_window=32768,
                cost_per_1k_tokens=0.0,
                latency_tier=LatencyTier.FAST,
                capabilities=["code", "completion", "chat"],
                is_active=True,
            ),
            ModelRecord(
                model_id="ollama/mistral",
                provider="ollama",
                context_window=32768,
                cost_per_1k_tokens=0.0,
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "code"],
                is_active=True,
            ),
            ModelRecord(
                model_id="ollama/codellama:7b",
                provider="ollama",
                context_window=16384,
                cost_per_1k_tokens=0.0,
                latency_tier=LatencyTier.FAST,
                capabilities=["code", "completion"],
                is_active=True,
            ),
            ModelRecord(
                model_id="ollama/llama3.2-vision",
                provider="ollama",
                context_window=128000,
                cost_per_1k_tokens=0.0,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "vision", "completion"],
                is_active=True,
            ),
            
            # ============ SPECIALIZED MODELS ============
            ModelRecord(
                model_id="gpt-4-turbo",
                provider="openai",
                context_window=128000,
                cost_per_1k_tokens=0.01,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "completion", "code", "function_call", "vision", "summarization"],
                is_active=True,
            ),
            ModelRecord(
                model_id="gemini-1.5-pro",
                provider="google",
                context_window=2097152,  # 2M context!
                cost_per_1k_tokens=0.00125,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["chat", "completion", "code", "vision", "summarization"],
                is_active=True,
            ),
            ModelRecord(
                model_id="gemini-1.5-flash",
                provider="google",
                context_window=1048576,  # 1M context
                cost_per_1k_tokens=0.000075,
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "code", "vision"],
                is_active=True,
            ),
            
            # ============ FUNCTION CALLING SPECIALISTS ============
            ModelRecord(
                model_id="mistral-small-latest",
                provider="mistral",
                context_window=32000,
                cost_per_1k_tokens=0.0002,
                latency_tier=LatencyTier.FAST,
                capabilities=["chat", "completion", "function_call"],
                is_active=True,
            ),
            
            # ============ CODE SPECIALISTS ============
            ModelRecord(
                model_id="deepseek-coder-33b",
                provider="deepseek",
                context_window=16000,
                cost_per_1k_tokens=0.00027,
                latency_tier=LatencyTier.MEDIUM,
                capabilities=["code", "completion", "chat"],
                is_active=True,
            ),
        ]
        
        # Filter out already registered models
        models_to_add = [m for m in new_models if m.model_id not in existing_ids]
        
        if not models_to_add:
            print("✅ All models already registered!")
            return
        
        print(f"\n📝 Registering {len(models_to_add)} new models...")
        print("=" * 90)
        
        # Group by type for organized output
        embedding_models = [m for m in models_to_add if "embedding" in m.capabilities]
        ollama_models = [m for m in models_to_add if m.provider == "ollama" and "embedding" not in m.capabilities]
        premium_models = [m for m in models_to_add if m.cost_per_1k_tokens > 0.005]
        other_models = [m for m in models_to_add if m not in embedding_models + ollama_models + premium_models]
        
        for category, models in [
            ("🔢 EMBEDDING MODELS (for retrieval)", embedding_models),
            ("🆓 OLLAMA LOCAL MODELS (free, local)", ollama_models),
            ("⚡ FAST & AFFORDABLE MODELS", other_models),
            ("💎 PREMIUM MODELS (high capability)", premium_models),
        ]:
            if models:
                print(f"\n{category}")
                for model in models:
                    session.add(model)
                    cost_display = "FREE" if model.cost_per_1k_tokens == 0 else f"${model.cost_per_1k_tokens:.5f}"
                    caps = ", ".join(model.capabilities[:3])
                    print(f"  ✓ {model.model_id:40s} | {model.latency_tier.value:6s} | {cost_display:10s} | {caps}")
        
        await session.commit()
        
        # Summary
        print("\n" + "=" * 90)
        print(f"✅ Successfully registered {len(models_to_add)} new models")
        
        # Show routing capabilities
        result = await session.execute(select(ModelRecord).where(ModelRecord.is_active == True))
        all_models = result.scalars().all()
        
        by_tier = {}
        by_provider = {}
        for m in all_models:
            by_tier[m.latency_tier] = by_tier.get(m.latency_tier, 0) + 1
            by_provider[m.provider] = by_provider.get(m.provider, 0) + 1
        
        print("\n📊 ROUTING CAPABILITIES:")
        print(f"   Total active models: {len(all_models)}")
        print(f"   By latency tier:")
        for tier, count in sorted(by_tier.items(), key=lambda x: x[0].value):
            print(f"      - {tier.value}: {count} models")
        print(f"   By provider:")
        for provider, count in sorted(by_provider.items()):
            print(f"      - {provider}: {count} models")
        
        free_models = [m for m in all_models if m.cost_per_1k_tokens == 0]
        print(f"   Cost optimization: {len(free_models)} free local models available")


async def verify_models():
    """Verify model registration and show routing examples."""
    async with primary_session_factory()() as session:
        # Show some routing scenarios
        print("\n" + "=" * 90)
        print("🎯 DYNAMIC ROUTING EXAMPLES:")
        
        # Fast code generation
        result = await session.execute(
            select(ModelRecord).where(
                ModelRecord.is_active == True,
                ModelRecord.latency_tier == LatencyTier.FAST,
            ).where(ModelRecord.capabilities.contains(["code"]))
        )
        code_models = result.scalars().all()
        print(f"\n⚡ Fast code generation ({len(code_models)} options):")
        for m in code_models[:3]:
            cost = "FREE" if m.cost_per_1k_tokens == 0 else f"${m.cost_per_1k_tokens:.5f}/1k"
            print(f"   → {m.model_id:40s} ({cost})")
        
        # Embedding models
        result = await session.execute(
            select(ModelRecord).where(
                ModelRecord.is_active == True,
            ).where(ModelRecord.capabilities.contains(["embedding"]))
        )
        embed_models = result.scalars().all()
        print(f"\n🔢 Embedding models ({len(embed_models)} options):")
        for m in embed_models:
            cost = "FREE" if m.cost_per_1k_tokens == 0 else f"${m.cost_per_1k_tokens:.5f}/1k"
            print(f"   → {m.model_id:40s} ({cost})")
        
        # Vision models
        result = await session.execute(
            select(ModelRecord).where(
                ModelRecord.is_active == True,
            ).where(ModelRecord.capabilities.contains(["vision"]))
        )
        vision_models = result.scalars().all()
        print(f"\n👁️  Vision models ({len(vision_models)} options):")
        for m in vision_models[:3]:
            cost = "FREE" if m.cost_per_1k_tokens == 0 else f"${m.cost_per_1k_tokens:.5f}/1k"
            print(f"   → {m.model_id:40s} ({cost})")


if __name__ == "__main__":
    asyncio.run(register_additional_models())
    asyncio.run(verify_models())
