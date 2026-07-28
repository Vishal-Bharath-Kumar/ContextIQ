"""
Test creating generation observations directly in Langfuse.
This bypasses LiteLLM's broken callback and creates the observations manually.
"""
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

# Load env FIRST
load_dotenv(Path(__file__).parent.parent / '.env')

from langfuse import Langfuse
from litellm import acompletion

async def main():
    print("\n" + "="*70)
    print("Langfuse Generation Test - Manual Observation Creation")
    print("="*70 + "\n")
    
    # Initialize Langfuse
    client = Langfuse()
    
    # Test cases
    tests = [
        {
            "name": "greeting",
            "prompt": "Say hello in exactly 5 words.",
            "max_tokens": 50,
        },
        {
            "name": "code-explanation",
            "prompt": "Explain what a Python function does in one sentence.",
            "max_tokens": 100,
        },
        {
            "name": "math",
            "prompt": "What is 7 x 8?",
            "max_tokens": 50,
        },
    ]
    
    for i, test in enumerate(tests, 1):
        print(f"Test {i}/{len(tests)}: {test['name']}")
        
        # Create trace
        trace = client.trace(
            name=f"ollama-test-{test['name']}",
            user_id="test-user",
            metadata={"test": "manual-generation", "index": i},
        )
        
        try:
            # Call LiteLLM
            response = await acompletion(
                model="ollama/llama3.2",
                messages=[{"role": "user", "content": test['prompt']}],
                max_tokens=test['max_tokens'],
                timeout=120,
            )
            
            # Extract usage
            usage = response.usage
            content = response.choices[0].message.content
            
            print(f"  ✅ Success: {usage.prompt_tokens} in + {usage.completion_tokens} out")
            
            # Manually create generation observation
            generation = trace.generation(
                name=f"ollama-generation-{test['name']}",
                model="ollama/llama3.2",
                input=test['prompt'],
                output=content,
                usage={
                    "input": usage.prompt_tokens,
                    "output": usage.completion_tokens,
                    "total": usage.total_tokens,
                    "unit": "TOKENS",
                },
                metadata={
                    "provider": "ollama",
                    "max_tokens": test['max_tokens'],
                },
            )
            
            print(f"     Trace ID: {trace.id}")
            print(f"     Generation ID: {generation.id}\n")
            
        except Exception as e:
            print(f"  ❌ Failed: {e}\n")
    
    # Flush
    print("Flushing to Langfuse...")
    client.flush()
    print("✅ Flushed\n")
    
    print("="*70)
    print("🎉 Complete!")
    print("="*70)
    print("\nCheck:")
    print("1. Langfuse Dashboard: https://cloud.langfuse.com")
    print("2. Admin Portal: http://localhost:3000/cost-analytics")
    print()

if __name__ == "__main__":
    asyncio.run(main())
