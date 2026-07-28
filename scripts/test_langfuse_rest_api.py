"""Test creating Langfuse generation observation via REST API."""
import os
import requests
import uuid
from datetime import datetime, UTC

public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
secret_key = os.getenv("LANGFUSE_SECRET_KEY")

# Create a trace first
trace_id = str(uuid.uuid4())
observation_id = str(uuid.uuid4())

trace_data = {
    "id": trace_id,
    "name": "rest-api-test",
    "timestamp": datetime.now(UTC).isoformat(),
    "input": {"prompt": "Test via REST API"},
    "output": "Test response via REST API",
    "metadata": {"source": "rest-api-test"},
}

print("Creating trace via REST API...")
trace_response = requests.post(
    "https://cloud.langfuse.com/api/public/traces",
    auth=(public_key, secret_key),
    json=trace_data,
)
print(f"  Trace response: {trace_response.status_code}")
if trace_response.status_code != 200:
    print(f"  Error: {trace_response.text}")

# Create a generation observation
generation_data = {
    "id": observation_id,
    "traceId": trace_id,
    "type": "GENERATION",
    "name": "rest-api-generation",
    "startTime": datetime.now(UTC).isoformat(),
    "endTime": datetime.now(UTC).isoformat(),
    "model": "test-model-rest",
    "modelParameters": {"temperature": 0.7},
    "input": [{"role": "user", "content": "Hello"}],
    "output": "Hello! How can I help you?",
    "usage": {
        "promptTokens": 10,
        "completionTokens": 20,
        "totalTokens": 30,
    },
    "metadata": {"test": "rest-api"},
}

print("Creating generation observation via REST API...")
gen_response = requests.post(
    "https://cloud.langfuse.com/api/public/generations",
    auth=(public_key, secret_key),
    json=generation_data,
)
print(f"  Generation response: {gen_response.status_code}")
if gen_response.status_code != 200:
    print(f"  Error: {gen_response.text}")

print("\nDone! Check Langfuse in 10 seconds.")
