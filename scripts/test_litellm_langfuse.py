"""
Test LiteLLM with Langfuse using global success_callback.
"""
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Load env FIRST
load_dotenv(Path(__file__).parent.parent / '.env')

# Set environment variables for LiteLLM Langfuse integration
os.environ['LANGFUSE_PUBLIC_KEY'] = os.getenv('LANGFUSE_PUBLIC_KEY', '')
os.environ['LANGFUSE_SECRET_KEY'] = os.getenv('LANGFUSE_SECRET_KEY', '')
os.environ['LANGFUSE_HOST'] = os.getenv('LANGFUSE_BASE_URL', 'https://cloud.langfuse.com')

# Import LiteLLM and enable Langfuse callback
import litellm
litellm.success_callback = ['langfuse']
litellm.set_verbose = False  # Reduce noise

from litellm import acompletion

async def main():
    print("\n" + "="*70)
    print("Testing Ollama → LiteLLM → Langfuse (Global Callback)")
    print("="*70 + "\n")
    
    tests = [
        {"name": "greeting", "prompt": "Say hello in 5 words", "max_tokens": 20},
        {"name": "math", "prompt": "What is 5 + 3?", "max_tokens": 15},
        {"name": "color", "prompt": "Name a primary color", "max_tokens": 5},
    ]
    
    total_input = 0
    total_output = 0
    success_count = 0
    
    for i, test in enumerate(tests, 1):
        print(f"Test {i}/{len(tests)}: {test['name']} - {test['prompt']}")
        
        try:
            response = await acompletion(
                model="ollama/llama3.2",
                messages=[{"role": "user", "content": test['prompt']}],
                max_tokens=test['max_tokens'],
                timeout=120,
            )
            
            usage = response.usage
            total_input += usage.prompt_tokens
            total_output += usage.completion_tokens
            success_count += 1
            
            print(f"  ✅ {usage.prompt_tokens} in + {usage.completion_tokens} out = {usage.total_tokens} tokens")
            print(f"     Response: {response.choices[0].message.content[:60]}...\n")
            
        except Exception as e:
            print(f"  ❌ Failed: {str(e)[:100]}\n")
    
    print("="*70)
    print(f"Summary: {success_count}/{len(tests)} successful")
    print(f"Total tokens: {total_input} input + {total_output} output = {total_input + total_output}")
    print("="*70 + "\n")
    
    # Give time for async callbacks to complete
    print("Waiting 3 seconds for Langfuse callbacks to finish...")
    await asyncio.sleep(3)
    print("✅ Done\n")
    
    print("Check:")
    print("1. Langfuse Dashboard: https://cloud.langfuse.com")
    print("   - Look for 'ollama/llama3.2' traces with token usage")
    print("2. Admin Portal: http://localhost:3000/cost-analytics")
    print("   - Should show tokens and model name")
    print()

if __name__ == "__main__":
    asyncio.run(main())
