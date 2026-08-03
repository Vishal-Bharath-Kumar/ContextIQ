"""Test Langfuse with shutdown() instead of flush()."""
import os
from langfuse import Langfuse

client = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host="https://cloud.langfuse.com",
)

print("Creating generation with all data upfront...")

generation = client.start_observation(
    name="test-shutdown-pattern",
    as_type="generation",
    model="test-model-shutdown",
    input=[{"role": "user", "content": "Test shutdown"}],
    output="Test response from shutdown pattern",
    usage_details={
        "prompt_tokens": 25,
        "completion_tokens": 50,
        "total_tokens": 75,
    },
    model_parameters={"temperature": 0.8},
    metadata={"test": "shutdown"},
)

print(f"  Generation ID: {generation.id}")
print("  Ending generation...")

generation.end()

print("  Calling shutdown() for blocking flush...")
client.shutdown()

print("\nDone! Data should be in Langfuse now.")
