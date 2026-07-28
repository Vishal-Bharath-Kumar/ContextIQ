"""Debug Langfuse generation observation creation."""
import os
from langfuse import Langfuse

# Initialize Langfuse
client = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host="https://cloud.langfuse.com",
)

print("Creating a test generation observation...")

# Try the context manager approach
with client.start_as_current_observation(
    name="test-generation",
    as_type="generation",
    model="test-model-123",
    input={"prompt": "Hello world"},
    metadata={"test": True},
) as generation:
    print("  Updating with output and usage...")
    generation.update(
        output="Test output",
        usage_details={
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
    )
    print("  Update complete")

print("Observation context exited")

# Flush to send data
print("Flushing...")
client.flush()
print("Flush complete")

print("\nTest generation observation created!")
print("Check Langfuse in 10 seconds to see if it has data.")
