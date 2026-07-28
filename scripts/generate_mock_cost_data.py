"""
Generate mock cost analytics data for testing.

This script creates fake Generation traces in Langfuse to test
the cost analytics dashboards without making actual LLM calls.

Run with:
    python3 scripts/generate_mock_cost_data.py
"""
import asyncio
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path
from uuid import uuid4

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# Import Langfuse directly
from langfuse import Langfuse


async def generate_mock_data():
    """Generate mock cost data in Langfuse."""
    
    print("\n" + "="*70)
    print("Mock Cost Analytics Data Generator")
    print("="*70 + "\n")
    
    # Initialize Langfuse
    print("1️⃣  Initializing Langfuse...")
    langfuse_client = Langfuse()
    print("✅ Langfuse initialized\n")
    
    # Mock data scenarios
    scenarios = [
        # Last 7 days - gpt-4o-mini usage
        {"model": "gpt-4o-mini", "days_ago": 0, "input_tokens": 1200, "output_tokens": 450, "count": 3},
        {"model": "gpt-4o-mini", "days_ago": 1, "input_tokens": 2100, "output_tokens": 780, "count": 5},
        {"model": "gpt-4o-mini", "days_ago": 2, "input_tokens": 1800, "output_tokens": 600, "count": 4},
        {"model": "gpt-4o-mini", "days_ago": 3, "input_tokens": 2400, "output_tokens": 900, "count": 6},
        {"model": "gpt-4o-mini", "days_ago": 4, "input_tokens": 1500, "output_tokens": 550, "count": 4},
        {"model": "gpt-4o-mini", "days_ago": 5, "input_tokens": 1900, "output_tokens": 700, "count": 5},
        {"model": "gpt-4o-mini", "days_ago": 6, "input_tokens": 1600, "output_tokens": 580, "count": 3},
        
        # Claude Sonnet usage (smaller amounts)
        {"model": "claude-3-5-sonnet-20241022", "days_ago": 0, "input_tokens": 800, "output_tokens": 350, "count": 2},
        {"model": "claude-3-5-sonnet-20241022", "days_ago": 1, "input_tokens": 1200, "output_tokens": 480, "count": 3},
        {"model": "claude-3-5-sonnet-20241022", "days_ago": 2, "input_tokens": 900, "output_tokens": 380, "count": 2},
        
        # GPT-4o (expensive, less usage)
        {"model": "gpt-4o", "days_ago": 0, "input_tokens": 500, "output_tokens": 200, "count": 1},
        {"model": "gpt-4o", "days_ago": 2, "input_tokens": 650, "output_tokens": 280, "count": 1},
    ]
    
    print("2️⃣  Generating mock traces...\n")
    
    total_traces = 0
    total_cost = 0.0
    
    for scenario in scenarios:
        model = scenario["model"]
        days_ago = scenario["days_ago"]
        input_tokens = scenario["input_tokens"]
        output_tokens = scenario["output_tokens"]
        count = scenario["count"]
        
        # Calculate date
        trace_date = datetime.now(UTC) - timedelta(days=days_ago)
        date_str = trace_date.strftime("%Y-%m-%d")
        
        # Simple cost calculation (approximate)
        if "gpt-4o-mini" in model:
            cost = (input_tokens * 0.150 / 1_000_000) + (output_tokens * 0.600 / 1_000_000)
        elif "gpt-4o" in model:
            cost = (input_tokens * 5.00 / 1_000_000) + (output_tokens * 15.00 / 1_000_000)
        elif "claude" in model:
            cost = (input_tokens * 3.00 / 1_000_000) + (output_tokens * 15.00 / 1_000_000)
        else:
            cost = (input_tokens * 1.00 / 1_000_000) + (output_tokens * 3.00 / 1_000_000)
        
        total_cost += cost * count
        
        print(f"  {date_str} | {model:35s} | {count} traces | ${cost * count:.6f}")
        
        # Create traces
        for i in range(count):
            trace_id = str(uuid4())
            gen_id = str(uuid4())
            
            # Create trace using score method (simpler approach for testing)
            generation = langfuse_client.generation(
                id=gen_id,
                name=f"mock-{model.split('/')[-1]}-test",
                model=model,
                input={"messages": [{"role": "user", "content": f"Mock test {i+1}"}]},
                output="Mock response",
                usage={
                    "input": input_tokens // count,
                    "output": output_tokens // count,
                    "total": (input_tokens + output_tokens) // count,
                    "unit": "TOKENS",
                    "totalCost": cost / count,
                },
                metadata={
                    "model_id": model,
                    "prompt_tokens": input_tokens // count,
                    "completion_tokens": output_tokens // count,
                    "cost_usd": cost / count,
                    "user_id": "test-user",
                    "team_id": "test-team",
                    "mock_data": True,
                    "days_ago": days_ago,
                },
                start_time=trace_date,
                end_time=trace_date + timedelta(seconds=2),
                session_id=f"session-{days_ago}",
                user_id="test-user",
            )
            
            total_traces += 1
    
    print(f"\n✅ Generated {total_traces} mock traces")
    print(f"   Estimated total cost: ${total_cost:.6f}\n")
    
    # Flush
    print("3️⃣  Flushing to Langfuse...")
    langfuse_client.flush()
    print("✅ Data sent to Langfuse\n")
    
    # Instructions
    print("="*70)
    print("🎉 Mock Data Generated!")
    print("="*70 + "\n")
    
    print("View the data in:\n")
    
    print("1️⃣  Admin Portal Cost Analytics")
    print("   URL: http://localhost:3001/cost-analytics")
    print("   Expected:")
    print("   ✓ Total Spend: $" + f"{total_cost:.6f}")
    print("   ✓ 3 models in the list:")
    print("      - gpt-4o-mini (most usage)")
    print("      - claude-3-5-sonnet-20241022")
    print("      - gpt-4o (expensive)")
    print("   ✓ Daily trend showing last 7 days")
    print("   ✓ Model comparison bars")
    print()
    
    print("2️⃣  Langfuse Dashboard")
    print("   URL: https://cloud.langfuse.com")
    print("   Expected:")
    print(f"   ✓ {total_traces} new traces")
    print("   ✓ Filter by tag: 'mock' or 'cost-test'")
    print("   ✓ Filter by session: session-0 through session-6")
    print("   ✓ Token usage and costs displayed")
    print()
    
    print("3️⃣  Query via API (if backend is running)")
    print("   # Get 7-day cost analytics")
    print("   curl -H 'Authorization: Bearer <token>' \\")
    print("     'http://localhost:8000/v1/models/cost-analytics?days=7'")
    print()
    
    print("4️⃣  Query Langfuse via CLI")
    print("   # List traces with 'mock' tag")
    print("   npx langfuse-cli api traces list --tags mock --limit 10")
    print()
    print("   # Get generations (observations)")
    print("   npx langfuse-cli api observations get-many --type GENERATION \\")
    print("     --limit 20")
    print()
    
    print("=" * 70)
    print("Note: Wait 1-2 minutes for data to sync, then refresh dashboards")
    print("=" * 70 + "\n")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(generate_mock_data())
    sys.exit(exit_code)
