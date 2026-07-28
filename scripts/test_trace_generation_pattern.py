"""Test Langfuse using trace() and generation() pattern."""
import os
from langfuse import Langfuse

client = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host="https://cloud.langfuse.com",
)

print("Creating trace and generation using trace() pattern...")

# Create a trace
trace = client.trace(
    name="test-trace-pattern",
    input={"request": "Test using trace() method"},
)

print(f"  Trace ID: {trace.id}")

# Create a generation within the trace
generation = trace.generation(
    name="test-generation-pattern",
    model="test-model-456",
    input=[{"role": "user", "content": "Hello"}],
    model_parameters={"temperature": 0.7, "max_tokens": 100},
)

print(f"  Generation ID: {generation.id}")

# Update the generation with output and usage
generation.update(
    output="Test output from trace pattern",
    usage={
        "promptTokens": 5,
        "completionTokens": 10,
        "totalTokens": 15,
    },
)

print("  Updated generation with output and usage")

# End the generation
generation.end()

print("  Ended generation")

# Flush
client.flush()

print("\nDone! Check Langfuse in 10 seconds.")
