"""Query Langfuse observations using Python SDK to see actual data."""
import os
from langfuse import Langfuse

client = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host="https://cloud.langfuse.com",
)

print("Querying GENERATION observations via Python SDK...")
response = client.api.observations.get_many(
    type="GENERATION",
    limit=3,
)

print(f"\nFound {len(response.data)} observations\n")

if response.data:
    obs = response.data[0]
    print("=== First Observation Attributes ===")
    attrs = [a for a in dir(obs) if not a.startswith('_')]
    for attr in sorted(attrs):
        try:
            value = getattr(obs, attr)
            if not callable(value):
                print(f"  {attr}: {value}")
        except Exception as e:
            print(f"  {attr}: <error: {e}>")

