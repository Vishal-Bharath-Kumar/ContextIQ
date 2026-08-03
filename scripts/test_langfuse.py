"""
Simple test script to verify Langfuse integration.

This script demonstrates basic Langfuse tracing functionality:
1. Initialize Langfuse
2. Create a simple traced function
3. Execute the function
4. Flush and verify traces

Run with:
    python scripts/test_langfuse.py
"""
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.observability.langfuse_integration import (
    setup_langfuse,
    teardown_langfuse,
    observe_llm,
    update_current_trace,
    update_current_observation,
)


@observe_llm(as_type="span", name="test-function")
async def test_traced_function(message: str) -> dict:
    """
    Example traced function.
    This will appear as a span in Langfuse.
    """
    # Add trace metadata
    update_current_trace(
        session_id="test-session-001",
        user_id="test-user",
        tags=["test", "demo"],
        metadata={"environment": "local"}
    )
    
    # Add observation metadata
    update_current_observation(
        input={"message": message},
        metadata={"message_length": len(message)}
    )
    
    # Simulate some work
    await asyncio.sleep(0.1)
    
    result = {
        "status": "success",
        "message": f"Processed: {message}",
        "length": len(message)
    }
    
    # Update output
    update_current_observation(output=result)
    
    return result


@observe_llm(as_type="span", name="nested-operation")
async def nested_function() -> str:
    """
    Example nested function.
    Will show hierarchy in Langfuse trace.
    """
    await asyncio.sleep(0.05)
    return "nested result"


@observe_llm(as_type="span", name="main-workflow")
async def main_workflow():
    """
    Main workflow that calls multiple traced functions.
    Demonstrates trace hierarchy.
    """
    print("🚀 Starting Langfuse integration test...")
    
    # Call traced function
    result1 = await test_traced_function("Hello Langfuse!")
    print(f"✓ Function 1 result: {result1}")
    
    # Call nested function
    result2 = await nested_function()
    print(f"✓ Function 2 result: {result2}")
    
    # Call traced function again with different input
    result3 = await test_traced_function("Testing observability")
    print(f"✓ Function 3 result: {result3}")
    
    print("✅ All test functions executed successfully")


async def main():
    """Initialize Langfuse, run tests, and cleanup."""
    
    print("\n" + "="*60)
    print("Langfuse Integration Test")
    print("="*60 + "\n")
    
    # Initialize Langfuse
    print("1️⃣  Initializing Langfuse...")
    langfuse = setup_langfuse()
    
    if langfuse is None:
        print("❌ Langfuse not configured!")
        print("\nPlease set these environment variables:")
        print("  LANGFUSE_PUBLIC_KEY=pk-lf-...")
        print("  LANGFUSE_SECRET_KEY=sk-lf-...")
        print("  LANGFUSE_BASE_URL=https://cloud.langfuse.com")
        print("  LANGFUSE_ENABLED=true")
        return 1
    
    print("✅ Langfuse initialized successfully")
    
    # Run test workflow
    print("\n2️⃣  Running test workflow...")
    try:
        await main_workflow()
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Flush traces
    print("\n3️⃣  Flushing traces to Langfuse...")
    teardown_langfuse()
    print("✅ Traces flushed")
    
    # Instructions for verification
    print("\n" + "="*60)
    print("🎉 Test completed successfully!")
    print("="*60)
    print("\nNext steps:")
    print("1. Open your Langfuse dashboard")
    print("2. Navigate to 'Traces' view")
    print("3. Look for traces with session_id='test-session-001'")
    print("4. Verify the trace hierarchy:")
    print("   - main-workflow (span)")
    print("     ├─ test-function (span)")
    print("     ├─ nested-operation (span)")
    print("     └─ test-function (span)")
    print("\nTo query traces via CLI:")
    print("  npx langfuse-cli api traces list --limit 5")
    print("\n")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
