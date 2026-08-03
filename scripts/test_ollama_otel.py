"""
Test Langfuse cost analytics using OpenTelemetry instrumentation.
This is the recommended approach for Langfuse v4.x.
"""
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Load env FIRST
load_dotenv(Path(__file__).parent.parent / '.env')

# Enable Langfuse OpenTelemetry instrumentation
from langfuse import Langfuse
client = Langfuse()

# Import LiteLLM AFTER Langfuse
from litellm import acompletion

async def test_ollama_with_langfuse():
    print("\n" + "="*70)
    print("Testing Ollama with Langfuse (OpenTelemetry)")
    print("="*70 + "\n")
    
    tests = [
        {"prompt": "Say hello in 5 words", "max_tokens": 20},
        {"prompt": "What is 2+2?", "max_tokens": 10},
        {"prompt": "Name a color", "max_tokens": 5},
    ]
    
    total_input = 0
    total_output = 0
    
    for i, test in enumerate(tests, 1):
        print(f"Test {i}/{len(tests)}: {test['prompt']}")
        
        try:
            # Set Langfuse env vars for LiteLLM to use
            os.environ["LANGFUSE_PUBLIC_KEY"] = os.getenv("LANGFUSE_PUBLIC_KEY", "")
            os.environ["LANGFUSE_SECRET_KEY"] = os.getenv("LANGFUSE_SECRET_KEY", "")
            os.environ["LANGFUSE_HOST"] = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
            
            response = await acompletion(
                model="ollama/llama3.2",
                messages=[{"role": "user", "content": test['prompt']}],
                max_tokens=test['max_tokens'],
                timeout=120,
                # Try adding metadata
                metadata={
                    "langfuse_tags": ["cost-analytics-test", "ollama"],
                    "langfuse_session_id": "test-session-ollama",
                },
            )
            
            usage = response.usage
            total_input += usage.prompt_tokens
            total_output += usage.completion_tokens
            
            print(f"  ✅ {usage.prompt_tokens} in + {usage.completion_tokens} out tokens\n")
            
        except Exception as e:
            print(f"  ❌ Failed: {e}\n")
    
    print(f"Total: {total_input} input + {total_output} output = {total_input + total_output} tokens\n")
    
    # Flush
    print("Flushing to Langfuse...")
    client.flush()
    print("✅ Done\n")
    
    print("="*70)
    print("Check:")
    print("1. Langfuse: https://cloud.langfuse.com")
    print("2. Admin Portal: http://localhost:3000/cost-analytics")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(test_ollama_with_langfuse())
