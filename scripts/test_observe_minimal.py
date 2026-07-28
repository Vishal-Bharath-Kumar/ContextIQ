"""
Minimal test of Langfuse observe decorator.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load env FIRST
load_dotenv(Path(__file__).parent.parent / '.env')

print("Environment variables loaded:")
print(f"  LANGFUSE_PUBLIC_KEY: {os.getenv('LANGFUSE_PUBLIC_KEY', '')[:8]}...")
print(f"  LANGFUSE_BASE_URL: {os.getenv('LANGFUSE_BASE_URL')}")
print()

# Import Langfuse AFTER env vars
from langfuse import observe
import time

@observe()
def simple_test_function(message: str) -> str:
    """Simple function with observe decorator."""
    time.sleep(0.1)
    return f"Processed: {message}"

@observe(as_type="span", name="main-test")
def main():
    """Main test function."""
    print("Running test with @observe decorator...")
    result = simple_test_function("Hello Langfuse!")
    print(f"Result: {result}")
    return result

if __name__ == "__main__":
    result = main()
    
    # Flush traces
    print("\nFlushing traces...")
    from langfuse import Langfuse
    client = Langfuse()
    client.flush()
    print("✅ Traces flushed")
    
    print("\nWaiting 3 seconds for Langfuse to process...")
    time.sleep(3)
    
    print("✅ Test complete!")
    print("\nCheck Langfuse dashboard: https://cloud.langfuse.com")
