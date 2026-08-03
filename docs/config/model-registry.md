# Model Registry - Quick Reference

## Overview

The Model Registry stores metadata about available AI models to enable the Dynamic Model Router to select the optimal model for each request based on cost, latency, capabilities, and context window requirements.

## Registered Models

7 models are currently registered:

| Model | Provider | Tier | Cost/1K Tokens | Context Window | Capabilities |
|-------|----------|------|----------------|----------------|--------------|
| deepseek-coder | deepseek | fast | $0.00014 | 16,000 | code, completion |
| gpt-4o-mini | openai | fast | $0.00015 | 128,000 | chat, completion, code, function_call, vision |
| claude-3-haiku-20240307 | anthropic | fast | $0.00025 | 200,000 | chat, completion, code, summarization |
| llama-3.1-70b | meta | medium | $0.00060 | 128,000 | chat, completion, code, summarization |
| mistral-large-latest | mistral | medium | $0.00200 | 128,000 | chat, completion, code, function_call |
| gpt-4o | openai | medium | $0.00250 | 128,000 | chat, completion, code, function_call, vision, summarization |
| claude-3-5-sonnet-20241022 | anthropic | medium | $0.00300 | 200,000 | chat, completion, code, function_call, vision, summarization |

## Latency Tiers

- **fast**: p95 latency < 500ms (e.g., gpt-4o-mini, claude-haiku, deepseek-coder)
- **medium**: p95 latency 500ms - 2s (e.g., gpt-4o, claude-sonnet)
- **slow**: p95 latency > 2s (e.g., o1, deep-reasoning models)

## Capabilities

Models can have the following capabilities:

- **chat**: Conversational turn completion
- **completion**: Single-turn text generation
- **embedding**: Vector embedding output
- **code**: Code-optimized generation
- **summarization**: Long-text compression
- **vision**: Image + text input
- **function_call**: Tool/function calling support

## API Endpoints

### List Active Models

```bash
GET /v1/models
```

Returns all active models sorted by cost (requires authentication).

### Register a New Model

```bash
POST /v1/models
Content-Type: application/json
Authorization: Bearer <token>

{
  "model_id": "gpt-4o-mini",
  "provider": "openai",
  "context_window": 128000,
  "cost_per_1k_tokens": 0.00015,
  "latency_tier": "fast",
  "capabilities": ["chat", "completion", "code", "function_call", "vision"],
  "is_active": true
}
```

### Update Model Status

```bash
PATCH /v1/models/{model_id}/status
Content-Type: application/json
Authorization: Bearer <token>

{
  "is_active": false
}
```

## Database Schema

```sql
CREATE TABLE model_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id VARCHAR(128) UNIQUE NOT NULL,
    provider VARCHAR(64) NOT NULL,
    context_window INTEGER NOT NULL,
    cost_per_1k_tokens FLOAT NOT NULL,
    latency_tier latency_tier_enum NOT NULL,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TYPE latency_tier_enum AS ENUM ('fast', 'medium', 'slow');
```

## Scripts

### Register Default Models

```bash
# Run inside the API container
docker compose exec api python -m scripts.registry.register_default_models
```

This script:
- Checks if models are already registered
- Registers 7 commonly used AI models
- Uses the ORM for type safety and validation
- Provides status feedback

### Verify Registration

```bash
docker compose exec api python -c "
import asyncio
from src.data.database import primary_session_factory
from sqlalchemy import text

async def main():
    async with primary_session_factory()() as session:
        result = await session.execute(
            text('SELECT model_id, provider, is_active FROM model_registry')
        )
        for row in result:
            print(f'{row[0]:35s} | {row[1]:12s} | active={row[2]}')

asyncio.run(main())
"
```

## Usage in Dynamic Model Router

The Dynamic Model Router (US-019) uses this registry to:

1. **Filter by capability**: Only consider models with required capabilities
2. **Apply constraints**: Filter by context window, latency tier, cost budget
3. **Rank candidates**: Sort by cost or latency based on user preferences
4. **Select optimal model**: Return the best match for the request

Example routing logic:

```python
# Pseudo-code
async def select_model(request):
    models = await get_active_models()
    
    # Filter by capabilities
    models = [m for m in models if request.required_capability in m.capabilities]
    
    # Filter by context window
    models = [m for m in models if m.context_window >= request.estimated_tokens]
    
    # Filter by latency tier
    if request.latency_requirement == "fast":
        models = [m for m in models if m.latency_tier == "fast"]
    
    # Sort by cost
    models.sort(key=lambda m: m.cost_per_1k_tokens)
    
    return models[0] if models else None
```

## Audit Trail

All model registry changes are logged to:
- `model_audit_log` table (model-specific events)
- `admin_audit_log` table (admin actions)

## Next Steps

1. Configure actual model API keys in Vault
2. Implement model health checks
3. Add real-time latency monitoring
4. Enable A/B testing between similar models
5. Add cost tracking and budgeting
