#!/usr/bin/env python3
"""Test LiteLLM model invocation with your configured API keys.

This script verifies that:
1. API keys are properly configured
2. LiteLLM can reach the provider APIs
3. The model invoker works end-to-end
4. The model registry integration is functional

Usage:
    docker compose exec api python scripts/registry/test_litellm_invocation.py
"""
import asyncio
import os
import sys

try:
    import litellm
    from src.data.database import primary_session_factory
    from src.model_invoker.invoker import LiteLLMInvoker
    from src.model_registry.repositories.model_repository import ModelRepository
    from src.model_registry.schemas.model_definition import LatencyTier
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("This script must be run inside the API container")
    sys.exit(1)


async def test_environment():
    """Test 1: Check if API keys are set."""
    print("=" * 80)
    print("TEST 1: Environment Variables")
    print("=" * 80)
    
    keys_to_check = {
        "OPENAI_API_KEY": "OpenAI (gpt-4o-mini, gpt-4o)",
        "ANTHROPIC_API_KEY": "Anthropic (claude models)",
        "DEEPSEEK_API_KEY": "DeepSeek (deepseek-coder)",
        "MISTRAL_API_KEY": "Mistral (mistral-large)",
    }
    
    configured = []
    missing = []
    
    for key, description in keys_to_check.items():
        value = os.getenv(key)
        if value:
            # Show first 10 chars only
            masked = value[:10] + "..." if len(value) > 10 else value
            print(f"✓ {key:25s} = {masked:15s} ({description})")
            configured.append(key)
        else:
            print(f"✗ {key:25s} = (not set) ({description})")
            missing.append(key)
    
    print()
    if configured:
        print(f"✅ {len(configured)} API key(s) configured")
    if missing:
        print(f"⚠️  {len(missing)} API key(s) missing - some models won't work")
    
    return bool(configured)


async def test_litellm_direct():
    """Test 2: Direct LiteLLM invocation."""
    print("\n" + "=" * 80)
    print("TEST 2: Direct LiteLLM Invocation")
    print("=" * 80)
    
    # Try OpenAI first, then Anthropic
    test_models = []
    if os.getenv("OPENAI_API_KEY"):
        test_models.append(("gpt-4o-mini", "OpenAI"))
    if os.getenv("ANTHROPIC_API_KEY"):
        test_models.append(("claude-3-haiku-20240307", "Anthropic"))
    
    if not test_models:
        print("⚠️  No API keys configured - skipping test")
        return False
    
    for model_id, provider in test_models:
        print(f"\nTesting {model_id} ({provider})...")
        try:
            response = await litellm.acompletion(
                model=model_id,
                messages=[{"role": "user", "content": "Say 'test successful' in 2 words"}],
                max_tokens=10,
                timeout=10.0,
            )
            content = response.choices[0].message.content
            print(f"✅ Response: {content}")
            print(f"   Tokens: {response.usage.prompt_tokens} in, {response.usage.completion_tokens} out")
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    return False


async def test_model_invoker():
    """Test 3: ContextIQ Model Invoker (wraps LiteLLM)."""
    print("\n" + "=" * 80)
    print("TEST 3: Model Invoker Integration")
    print("=" * 80)
    
    # Determine which model to test
    if os.getenv("OPENAI_API_KEY"):
        model_id = "gpt-4o-mini"
        latency = LatencyTier.FAST
    elif os.getenv("ANTHROPIC_API_KEY"):
        model_id = "claude-3-haiku-20240307"
        latency = LatencyTier.FAST
    else:
        print("⚠️  No API keys configured - skipping test")
        return False
    
    print(f"\nTesting ModelInvoker with {model_id}...")
    try:
        invoker = LiteLLMInvoker()
        response = await invoker.invoke(
            model_id=model_id,
            messages=[{"role": "user", "content": "Explain ContextIQ in exactly 5 words"}],
            token_budget=20,
            latency_tier=latency,
        )
        print(f"✅ Model: {response.model_id}")
        print(f"   Response: {response.content}")
        print(f"   Tokens: {response.input_tokens} in, {response.output_tokens} out")
        print(f"   Finish: {response.finish_reason}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_registry_integration():
    """Test 4: Full integration with model registry."""
    print("\n" + "=" * 80)
    print("TEST 4: Model Registry Integration")
    print("=" * 80)
    
    async with primary_session_factory()() as session:
        repo = ModelRepository(session)
        
        # Get all active models
        models = await repo.list_active()
        print(f"\nFound {len(models)} registered models:")
        
        # Check which ones have API keys
        available = []
        unavailable = []
        
        for model in models:
            # Determine if we have the API key for this model
            has_key = False
            if "gpt" in model.model_id.lower() and os.getenv("OPENAI_API_KEY"):
                has_key = True
            elif "claude" in model.model_id.lower() and os.getenv("ANTHROPIC_API_KEY"):
                has_key = True
            elif "deepseek" in model.model_id.lower() and os.getenv("DEEPSEEK_API_KEY"):
                has_key = True
            elif "mistral" in model.model_id.lower() and os.getenv("MISTRAL_API_KEY"):
                has_key = True
            
            status = "✓" if has_key else "✗"
            print(f"  {status} {model.model_id:35s} | {model.provider:12s} | ${model.cost_per_1k_tokens:.5f}")
            
            if has_key:
                available.append(model)
            else:
                unavailable.append(model)
        
        print(f"\n✅ {len(available)} model(s) ready to use (API keys configured)")
        print(f"⚠️  {len(unavailable)} model(s) unavailable (API keys missing)")
        
        # Try to invoke the cheapest available model
        if available:
            cheapest = min(available, key=lambda m: m.cost_per_1k_tokens)
            print(f"\n🎯 Testing cheapest available model: {cheapest.model_id}")
            
            try:
                invoker = LiteLLMInvoker()
                response = await invoker.invoke(
                    model_id=cheapest.model_id,
                    messages=[{"role": "user", "content": "Test message - reply in 3 words"}],
                    token_budget=10,
                    latency_tier=cheapest.latency_tier,
                )
                print(f"   ✅ Response: {response.content}")
                print(f"   Cost: ~${cheapest.cost_per_1k_tokens * response.input_tokens / 1000:.6f} for this request")
                return True
            except Exception as e:
                print(f"   ❌ Error: {e}")
                return False
        else:
            print("\n⚠️  No models available - configure API keys first")
            return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("LITELLM MODEL INVOCATION TEST")
    print("=" * 80)
    
    results = {}
    
    # Test 1: Environment
    results["environment"] = await test_environment()
    
    if not results["environment"]:
        print("\n" + "=" * 80)
        print("⚠️  NO API KEYS CONFIGURED")
        print("=" * 80)
        print("\nTo configure API keys:")
        print("1. Copy .env.local to .env")
        print("2. Add your API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)")
        print("3. Restart services: docker compose down && docker compose up -d")
        print("\nSee docs/config/model-api-configuration.md for details")
        return
    
    # Test 2: Direct LiteLLM
    results["litellm"] = await test_litellm_direct()
    
    # Test 3: Model Invoker
    results["invoker"] = await test_model_invoker()
    
    # Test 4: Registry Integration
    results["registry"] = await test_registry_integration()
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status:10s} {test_name.title()}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n" + "=" * 80)
        print("🎉 ALL TESTS PASSED - MODEL INVOCATION IS WORKING!")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print("⚠️  SOME TESTS FAILED - CHECK CONFIGURATION")
        print("=" * 80)
        print("\nSee docs/config/model-api-configuration.md for troubleshooting")


if __name__ == "__main__":
    asyncio.run(main())
