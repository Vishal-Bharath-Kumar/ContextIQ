"""Test Ollama integration with ContextIQ.

This script verifies:
1. Ollama is running and accessible
2. Models are available
3. LiteLLM can invoke Ollama models
4. Model registry integration works
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")

import litellm
from src.data.database import primary_session_factory
from src.model_invoker.invoker import LiteLLMInvoker
from src.model_registry.repositories.model_repository import ModelRepository
from src.model_registry.schemas.model_definition import LatencyTier


async def test_ollama_connection():
    """Test 1: Check if Ollama is accessible."""
    print("=" * 80)
    print("TEST 1: Ollama Connection")
    print("=" * 80)
    
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    print(f"\nOllama base URL: {base_url}")
    
    try:
        # Try to connect to Ollama
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url.replace('host.docker.internal', 'localhost')}/api/version") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ Ollama is running: version {data.get('version', 'unknown')}")
                    return True
                else:
                    print(f"❌ Ollama returned status {resp.status}")
                    return False
    except Exception as e:
        print(f"❌ Cannot connect to Ollama: {e}")
        print("\nMake sure Ollama is running:")
        print("  ollama serve")
        return False


async def test_direct_ollama():
    """Test 2: Direct Ollama API call."""
    print("\n" + "=" * 80)
    print("TEST 2: Direct Ollama API")
    print("=" * 80)
    
    print("\nTesting ollama/llama3.2...")
    
    try:
        import aiohttp
        import json
        
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": "llama3.2",
            "prompt": "Say hello in exactly 2 words",
            "stream": False
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response = data.get("response", "")
                    print(f"✅ Response: {response}")
                    return True
                else:
                    print(f"❌ Status {resp.status}: {await resp.text()}")
                    return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def test_litellm_ollama():
    """Test 3: LiteLLM with Ollama."""
    print("\n" + "=" * 80)
    print("TEST 3: LiteLLM → Ollama Integration")
    print("=" * 80)
    
    # Set Ollama base URL for LiteLLM
    os.environ["OLLAMA_BASE_URL"] = os.getenv(
        "OLLAMA_BASE_URL", 
        "http://host.docker.internal:11434"
    )
    
    print(f"\nLiteLLM OLLAMA_BASE_URL: {os.environ['OLLAMA_BASE_URL']}")
    print("Testing ollama/llama3.2 via LiteLLM...")
    
    try:
        response = await litellm.acompletion(
            model="ollama/llama3.2",
            messages=[{"role": "user", "content": "Say HELLO OLLAMA"}],
            max_tokens=10,
            timeout=30.0,
        )
        
        content = response.choices[0].message.content
        tokens_in = response.usage.prompt_tokens
        tokens_out = response.usage.completion_tokens
        
        print(f"✅ SUCCESS!")
        print(f"   Response: {content}")
        print(f"   Tokens: {tokens_in} in, {tokens_out} out")
        print(f"   Cost: $0.00 (local model)")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Is Ollama running? Check: curl http://localhost:11434/api/version")
        print("2. Is llama3.2 pulled? Check: ollama list")
        print("3. Try manually: ollama run llama3.2 'hello'")
        return False


async def test_model_invoker():
    """Test 4: ContextIQ Model Invoker."""
    print("\n" + "=" * 80)
    print("TEST 4: ContextIQ Model Invoker")
    print("=" * 80)
    
    # Ensure Ollama base URL is set
    os.environ["OLLAMA_BASE_URL"] = os.getenv(
        "OLLAMA_BASE_URL",
        "http://host.docker.internal:11434"
    )
    
    print("\nTesting ModelInvoker with ollama/llama3.2...")
    
    try:
        invoker = LiteLLMInvoker()
        response = await invoker.invoke(
            model_id="ollama/llama3.2",
            messages=[{"role": "user", "content": "Explain ContextIQ in 5 words"}],
            token_budget=20,
            latency_tier=LatencyTier.FAST,
        )
        
        print(f"✅ SUCCESS!")
        print(f"   Model: {response.model_id}")
        print(f"   Response: {response.content}")
        print(f"   Tokens: {response.input_tokens} in, {response.output_tokens} out")
        print(f"   Cost: $0.00")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_registry_integration():
    """Test 5: Full registry integration."""
    print("\n" + "=" * 80)
    print("TEST 5: Model Registry Integration")
    print("=" * 80)
    
    os.environ["OLLAMA_BASE_URL"] = os.getenv(
        "OLLAMA_BASE_URL",
        "http://host.docker.internal:11434"
    )
    
    async with primary_session_factory()() as session:
        repo = ModelRepository(session)
        
        # Get all Ollama models
        all_models = await repo.list_active()
        ollama_models = [m for m in all_models if m.provider == "ollama"]
        
        print(f"\nFound {len(ollama_models)} Ollama models in registry:")
        
        for model in ollama_models:
            caps = ", ".join(model.capabilities)
            print(f"  ✓ {model.model_id:35s} | {caps}")
        
        if not ollama_models:
            print("\n❌ No Ollama models found in registry!")
            print("   Run: docker compose exec api python scripts/registry/register_ollama_models.py")
            return False
        
        # Test the cheapest (all are $0!)
        cheapest = ollama_models[0]
        print(f"\n🎯 Testing: {cheapest.model_id}")
        
        try:
            invoker = LiteLLMInvoker()
            response = await invoker.invoke(
                model_id=cheapest.model_id,
                messages=[{"role": "user", "content": "Test - reply in 3 words"}],
                token_budget=10,
                latency_tier=cheapest.latency_tier,
            )
            
            print(f"   ✅ Response: {response.content}")
            print(f"   Cost: $0.00 (local inference)")
            return True
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("OLLAMA INTEGRATION TEST")
    print("=" * 80)
    
    results = {}
    
    # Run tests sequentially
    results["connection"] = await test_ollama_connection()
    
    if not results["connection"]:
        print("\n⚠️  Ollama is not running. Start it with:")
        print("   ollama serve")
        return
    
    results["direct_api"] = await test_direct_ollama()
    results["litellm"] = await test_litellm_ollama()
    results["invoker"] = await test_model_invoker()
    results["registry"] = await test_registry_integration()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status:10s} {test_name.replace('_', ' ').title()}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n" + "=" * 80)
        print("🎉 ALL TESTS PASSED - OLLAMA INTEGRATION WORKING!")
        print("=" * 80)
        print("\n✅ Benefits of using Ollama:")
        print("   • $0.00 cost - runs entirely on your machine")
        print("   • No API rate limits")
        print("   • Full privacy - data never leaves your computer")
        print("   • Works offline")
        print("   • Fast inference on local hardware")
    else:
        print("\n" + "=" * 80)
        print("⚠️  SOME TESTS FAILED")
        print("=" * 80)
        print("\nTroubleshooting:")
        print("1. Start Ollama: ollama serve")
        print("2. Pull models: ollama pull llama3.2")
        print("3. Register models: python scripts/registry/register_ollama_models.py")


if __name__ == "__main__":
    asyncio.run(main())
