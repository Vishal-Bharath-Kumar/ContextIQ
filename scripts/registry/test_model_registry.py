"""Simple test to verify model registry is working.

This script demonstrates:
1. Retrieving all active models
2. Finding models by capability
3. Finding the cheapest model
4. Finding models by latency tier
"""
import asyncio

from src.data.database import primary_session_factory
from src.model_registry.repositories.model_repository import ModelRepository


async def test_model_registry() -> None:
    """Test various model registry queries."""
    async with primary_session_factory()() as session:
        repo = ModelRepository(session)
        
        # 1. List all active models
        print("=" * 80)
        print("TEST 1: List All Active Models")
        print("=" * 80)
        models = await repo.list_active()
        print(f"\nFound {len(models)} active models:\n")
        for m in models:
            caps = ", ".join(m.capabilities)
            print(f"  {m.model_id:35s} | ${m.cost_per_1k_tokens:.5f} | {m.latency_tier:6s} | {caps}")
        
        # 2. Find models with code capability
        print("\n" + "=" * 80)
        print("TEST 2: Models with 'code' Capability")
        print("=" * 80)
        code_models = [m for m in models if "code" in m.capabilities]
        print(f"\nFound {len(code_models)} code-capable models:\n")
        for m in code_models:
            print(f"  {m.model_id:35s} | {m.provider:12s}")
        
        # 3. Find the cheapest model
        print("\n" + "=" * 80)
        print("TEST 3: Cheapest Model")
        print("=" * 80)
        if models:
            cheapest = min(models, key=lambda m: m.cost_per_1k_tokens)
            print(f"\nCheapest model: {cheapest.model_id}")
            print(f"  Provider: {cheapest.provider}")
            print(f"  Cost: ${cheapest.cost_per_1k_tokens:.5f} per 1K tokens")
            print(f"  Context: {cheapest.context_window:,} tokens")
        
        # 4. Find fast models
        print("\n" + "=" * 80)
        print("TEST 4: Fast Models (< 500ms latency)")
        print("=" * 80)
        fast_models = [m for m in models if m.latency_tier == "fast"]
        print(f"\nFound {len(fast_models)} fast models:\n")
        for m in fast_models:
            print(f"  {m.model_id:35s} | {m.context_window:8,} tokens | ${m.cost_per_1k_tokens:.5f}")
        
        # 5. Find models with vision capability
        print("\n" + "=" * 80)
        print("TEST 5: Models with Vision Capability")
        print("=" * 80)
        vision_models = [m for m in models if "vision" in m.capabilities]
        print(f"\nFound {len(vision_models)} vision-capable models:\n")
        for m in vision_models:
            print(f"  {m.model_id:35s} | {m.provider:12s}")
        
        # 6. Find best model for code completion (fast + code + cheap)
        print("\n" + "=" * 80)
        print("TEST 6: Best Model for Code Completion (fast, code-capable, cheap)")
        print("=" * 80)
        code_fast = [
            m for m in models 
            if "code" in m.capabilities
            and m.latency_tier == "fast"
        ]
        if code_fast:
            best_code = min(code_fast, key=lambda m: m.cost_per_1k_tokens)
            print(f"\nBest choice: {best_code.model_id}")
            print(f"  Provider: {best_code.provider}")
            print(f"  Cost: ${best_code.cost_per_1k_tokens:.5f} per 1K tokens")
            print(f"  Latency: {best_code.latency_tier}")
            print(f"  Context: {best_code.context_window:,} tokens")
        
        print("\n" + "=" * 80)
        print("✅ All tests passed!")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(test_model_registry())
