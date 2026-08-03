# Langfuse Integration Issue - Data Not Persisting

## Problem Summary

Cost analytics in the admin portal displays $0.00 and 0 tokens despite successful LLM calls with Ollama. The root cause is that Langfuse GENERATION observations are created but **all data fields remain null**.

## Investigation Timeline

### What Works ✅
- Langfuse SDK initializes successfully
- API authentication is valid (pk-lf-1bb2f22c..., sk-lf-6d757fa2...)
- Traces are visible in Langfuse cloud dashboard
- GENERATION observations are created (confirmed via `npx langfuse-cli api observations list`)
- LLM calls execute successfully with token counts (e.g., 204 tokens across 3 test calls)

### What Fails ❌
- **All observation data fields are null**: `provided_model_name`, `usage_details`, `input`, `output`, `name`
- Backend API query returns observations but aggregates to 0 tokens and $0.00
- Admin portal displays "No data available"

### Attempted Solutions

1. **@observe Decorator** (Python SDK v4.14.x)
   - Created SPAN observations (not GENERATION)
   - Backend queries for `type="GENERATION"` specifically
   - **Result**: Observations created but wrong type for cost analytics

2. **start_observation() + update()** (Python SDK v4.14.x)
   - Used context manager pattern
   - Called `.update()` with `usage_details`, `output`
   - Called `.end()` and `.flush()`
   - **Result**: Observations created but all data fields null

3. **REST API Direct Calls** (`/api/public/traces` + `/api/public/generations`)
   - Returns HTTP 200 for both endpoints
   - Used correct field names: `model`, `usage`, `input`, `output`
   - **Result**: Observations created but data not indexed/queryable

4. **Ingestion Batch API** (`/api/public/ingestion`)
   - Used async batch ingestion endpoint
   - Sent both trace and observation in single batch
   - Waited 30+ seconds for async processing
   - **Result**: No observations found with data

## Current State

```bash
# Query Result (via CLI):
npx langfuse-cli api observations list --type GENERATION
{
  "id": "6d17162ce77d82a3",
  "name": null,
  "model": null,
  "provided_model_name": null,
  "usage_details": null,
  "input": null,
  "output": null
}
```

```python
# Backend Query (analytics_service.py):
response = langfuse.api.observations.get_many(
    type="GENERATION",
    from_start_time=start_dt,
    limit=1000,
)

for obs in response.data:
    model_id = obs.provided_model_name or "unknown"  # <- NULL, becomes "unknown"
    usage_details = obs.usage_details or {}  # <- NULL, becomes {}
    total_tokens = usage_details.get("total", 0)  # <- 0
```

## Environment

- **Langfuse SDK**: v4.14.1 (Python)
- **Python**: 3.12.13 (Homebrew venv at /tmp/venv312)
- **Langfuse Cloud**: https://cloud.langfuse.com
- **Project ID**: cms4cvynh0o68ad0dk1n5bm6a
- **LLM Provider**: Ollama (local, localhost:11434)
- **Models**: llama3.2, phi3

## Hypothesis

The Langfuse Python SDK v4.14.x has a **data persistence bug** where:
1. Observation entities are created (visible in lists)
2. Data fields are NOT sent or NOT stored
3. Queries return observations with all data fields as `null`

This affects **both**:
- SDK methods (`start_observation`, `update`, context managers)
- REST API calls (`/api/public/generations`, `/api/public/ingestion`)

## Recommended Actions

### Option 1: Downgrade Langfuse SDK (Recommended)
```bash
pip install "langfuse<4.0.0"
```
Try Langfuse v3.x which uses different internal APIs.

### Option 2: File Bug Report
Report to https://github.com/langfuse/langfuse-python/issues with:
- Observation IDs showing null data
- SDK version: 4.14.1
- Reproduction steps from scripts/test_cost_analytics_ollama.py

### Option 3: Alternative Observability
Temporarily use:
- LangSmith (LangChain's observability)
- Weights & Biases (W&B)
- Custom logging to PostgreSQL

### Option 4: Manual Token Tracking
Bypass Langfuse for cost analytics:
- Log token usage directly to database
- Create custom analytics dashboard
- Use for interim solution until Langfuse fixed

## Files Modified

### Implementation Files
- `src/observability/langfuse_integration/` - Integration module
- `src/model_invoker/invoker.py` - Manual REST API calls
- `src/main.py` - Lifecycle management
- `scripts/test_cost_analytics_ollama.py` - Test script

### Documentation
- `docs/LANGFUSE_INTEGRATION.md` - Integration guide
- `docs/COST_ANALYTICS_ARCHITECTURE.md` - Architecture explanation
- `LANGFUSE_DATA_PERSISTENCE_ISSUE.md` - This file

## Next Steps

**IMMEDIATE**: User should decide which option to pursue:
1. Try SDK downgrade to v3.x
2. File bug report and wait for fix
3. Switch to alternative observability solution
4. Implement custom token tracking

**LONG-TERM**: Monitor Langfuse GitHub releases for fixes to v4.14.x data persistence issue.
