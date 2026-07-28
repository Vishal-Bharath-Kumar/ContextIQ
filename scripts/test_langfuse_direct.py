"""
Direct Langfuse test - verify data is actually sent.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load env
load_dotenv(Path(__file__).parent.parent / '.env')

from langfuse import Langfuse
from datetime import datetime

print("Initializing Langfuse SDK...")
client = Langfuse()

print("Creating test trace...")
trace = client.trace(
    name="ollama-cost-test",
    user_id="test-user",
    session_id="direct-test-session",
    metadata={"test": "direct", "purpose": "cost-analytics"},
)

print("Creating generation with cost data...")
generation = trace.generation(
    name="ollama-llama3.2-test",
    model="ollama/llama3.2",
    input={"messages": [{"role": "user", "content": "Test prompt"}]},
    output="Test response",
    usage={
        "input": 50,
        "output": 25,
        "total": 75,
        "unit": "TOKENS",
    },
    metadata={
        "model_id": "ollama/llama3.2",
        "provider": "ollama",
        "test_type": "direct",
    },
)

print("Flushing to Langfuse...")
client.flush()

print("\n✅ Test trace created!")
print(f"Trace ID: {trace.id}")
print(f"Generation ID: {generation.id}")
print("\nCheck Langfuse dashboard:")
print("  https://cloud.langfuse.com")
print(f"  Session: direct-test-session")
print(f"  Trace ID: {trace.id}")
