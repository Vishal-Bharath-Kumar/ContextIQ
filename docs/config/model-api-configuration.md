# Model API Configuration Guide

## Overview

ContextIQ uses a **two-layer architecture** for AI model management:

1. **Model Registry** (database) - Stores model metadata (cost, latency, capabilities)
2. **LiteLLM Gateway** - Actually invokes the models using provider API keys

You've completed step 1 (registering models). Now you need step 2 (configuring API access).

---

## Architecture Flow

```
User Request
     ↓
Dynamic Model Router (queries model_registry)
     ↓
Selects optimal model based on cost/latency/capabilities
     ↓
LiteLLM Invoker (reads API keys from environment)
     ↓
Calls actual provider API (OpenAI, Anthropic, etc.)
     ↓
Returns response
```

---

## Current Status

✅ **Model Registry**: 7 models registered with metadata  
⚠️ **API Keys**: Need to be configured for actual model invocation

---

## How LiteLLM Works

**LiteLLM** is an AI Gateway that provides a unified interface to 100+ LLM providers. It:

- Translates the model registry's `model_id` to the actual provider API
- Handles authentication via environment variables
- Provides retry logic, rate limiting, and fallback
- Supports OpenAI, Anthropic, Azure, Google, local models, and more

### Model ID → Provider Mapping

The `model_id` in your registry maps directly to LiteLLM's model naming:

| Registry model_id | LiteLLM Provider | API Key Required |
|-------------------|------------------|------------------|
| gpt-4o-mini | OpenAI | OPENAI_API_KEY |
| gpt-4o | OpenAI | OPENAI_API_KEY |
| claude-3-haiku-20240307 | Anthropic | ANTHROPIC_API_KEY |
| claude-3-5-sonnet-20241022 | Anthropic | ANTHROPIC_API_KEY |
| deepseek-coder | DeepSeek | DEEPSEEK_API_KEY |
| llama-3.1-70b | Various (Ollama/vLLM/Groq) | Depends on deployment |
| mistral-large-latest | Mistral | MISTRAL_API_KEY |

---

## API Key Configuration

### Step 1: Create .env File

Your `.env.local` file shows the template. Create the actual `.env` file:

```bash
cd /Users/vishalbharathkumar/Hackathon/ContextIQ
cp .env.local .env
```

### Step 2: Add API Keys

Edit `.env` and add your API keys:

```bash
# OpenAI (for gpt-4o-mini, gpt-4o)
OPENAI_API_KEY=sk-proj-YOUR_OPENAI_KEY_HERE

# Anthropic (for claude-haiku, claude-sonnet)
ANTHROPIC_API_KEY=sk-ant-YOUR_ANTHROPIC_KEY_HERE

# DeepSeek (for deepseek-coder)
DEEPSEEK_API_KEY=YOUR_DEEPSEEK_KEY_HERE

# Mistral (for mistral-large-latest)
MISTRAL_API_KEY=YOUR_MISTRAL_KEY_HERE
```

### Step 3: Update docker-compose.yml

The API service needs to read these environment variables. Add them to the `api` service:

```yaml
api:
  environment:
    # ... existing env vars ...
    OPENAI_API_KEY: ${OPENAI_API_KEY}
    ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}
    MISTRAL_API_KEY: ${MISTRAL_API_KEY:-}
```

The `:-` syntax means "use the value if set, otherwise empty string" (makes them optional).

### Step 4: Restart Services

```bash
docker compose down
docker compose up -d api
```

---

## Getting API Keys

### OpenAI
1. Go to https://platform.openai.com/api-keys
2. Click "Create new secret key"
3. Copy the key (starts with `sk-proj-...` or `sk-...`)
4. Add to `.env` as `OPENAI_API_KEY`

**Cost**: Pay-as-you-go, ~$0.15/1M tokens for gpt-4o-mini

### Anthropic (Claude)
1. Go to https://console.anthropic.com/settings/keys
2. Click "Create Key"
3. Copy the key (starts with `sk-ant-...`)
4. Add to `.env` as `ANTHROPIC_API_KEY`

**Cost**: Pay-as-you-go, ~$0.25/1M tokens for Claude Haiku

### DeepSeek
1. Go to https://platform.deepseek.com/api_keys
2. Create an API key
3. Add to `.env` as `DEEPSEEK_API_KEY`

**Cost**: Very cheap, ~$0.14/1M tokens

### Mistral
1. Go to https://console.mistral.ai/api-keys/
2. Create a key
3. Add to `.env` as `MISTRAL_API_KEY`

**Cost**: ~$2/1M tokens for mistral-large

---

## Alternative: Use Local Models (No API Keys Required)

If you don't want to use paid APIs, you can use **local models** via Ollama or vLLM:

### Option 1: Ollama

```bash
# Install Ollama
brew install ollama  # macOS

# Pull models
ollama pull llama3.1:70b
ollama pull deepseek-coder
ollama pull mistral

# Update .env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Update the model registry to use Ollama prefixes:

```python
# Instead of "llama-3.1-70b", use "ollama/llama3.1:70b"
# Instead of "deepseek-coder", use "ollama/deepseek-coder"
```

### Option 2: Azure OpenAI (Enterprise)

If you have an Azure OpenAI subscription:

```bash
AZURE_OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-05-01-preview
```

Update model IDs to use Azure format:
- `azure/gpt-4o-mini`
- `azure/gpt-4o`

---

## Verification

### Test 1: Check Environment Variables

```bash
docker compose exec api python -c "
import os
print('OPENAI_API_KEY set:', bool(os.getenv('OPENAI_API_KEY')))
print('ANTHROPIC_API_KEY set:', bool(os.getenv('ANTHROPIC_API_KEY')))
"
```

### Test 2: Test LiteLLM Invocation

```bash
docker compose exec api python -c "
import asyncio
import litellm

async def test():
    try:
        response = await litellm.acompletion(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': 'Say hello'}],
            max_tokens=10
        )
        print('✅ LiteLLM working!')
        print('Response:', response.choices[0].message.content)
    except Exception as e:
        print('❌ Error:', e)

asyncio.run(test())
"
```

### Test 3: Full Integration Test

```bash
docker compose exec api python -c "
import asyncio
from src.model_invoker.invoker import LiteLLMInvoker
from src.model_registry.schemas.model_definition import LatencyTier

async def test():
    invoker = LiteLLMInvoker()
    response = await invoker.invoke(
        model_id='gpt-4o-mini',
        messages=[{'role': 'user', 'content': 'Explain ContextIQ in 10 words'}],
        token_budget=20,
        latency_tier=LatencyTier.FAST
    )
    print(f'✅ Model: {response.model_id}')
    print(f'Response: {response.content}')
    print(f'Tokens: {response.input_tokens} in, {response.output_tokens} out')

asyncio.run(test())
"
```

---

## Security Best Practices

### 1. Never Commit .env

```bash
# Ensure .env is in .gitignore
echo ".env" >> .gitignore
git rm --cached .env 2>/dev/null || true
```

### 2. Use Vault for Production

For production, store API keys in HashiCorp Vault:

```bash
# Store in Vault
vault kv put secret/model-providers/openai api_key=sk-proj-...
vault kv put secret/model-providers/anthropic api_key=sk-ant-...

# Update docker-compose to read from Vault
# (See docs/config/vault-integration.md)
```

### 3. Rotate Keys Regularly

- OpenAI: Rotate every 90 days
- Anthropic: Rotate every 90 days
- Use separate keys for dev/staging/prod

### 4. Monitor Usage

Track API usage in each provider's dashboard:
- OpenAI: https://platform.openai.com/usage
- Anthropic: https://console.anthropic.com/settings/billing

---

## Cost Management

### Set Budget Limits

In `.env`:

```bash
# LiteLLM budget tracking
LITELLM_BUDGET_ENABLED=true
LITELLM_MAX_BUDGET=100.0  # USD per month
```

### Monitor Costs

```bash
docker compose exec api python -c "
import asyncio
from src.data.database import primary_session_factory
from sqlalchemy import text

async def main():
    async with primary_session_factory()() as session:
        # Check recent model usage
        result = await session.execute(
            text('''
                SELECT model_id, COUNT(*) as calls, 
                       SUM(input_tokens) as total_in,
                       SUM(output_tokens) as total_out
                FROM model_audit_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY model_id
                ORDER BY calls DESC
            ''')
        )
        print('24-hour model usage:')
        for row in result:
            print(f'{row[0]:30s} | {row[1]:5d} calls | {row[2]:8d} in | {row[3]:8d} out')

asyncio.run(main())
"
```

---

## Troubleshooting

### Error: "Invalid API key"

1. Check the key format (should start with `sk-proj-`, `sk-ant-`, etc.)
2. Verify the key is active in the provider's dashboard
3. Check environment variables are loaded: `docker compose exec api env | grep API_KEY`

### Error: "Rate limit exceeded"

1. Check your provider's rate limits
2. Implement backoff in the fallback invoker
3. Upgrade to a higher tier plan

### Error: "Model not found"

1. Verify the `model_id` in the registry matches LiteLLM's naming
2. Check if the model requires a specific API version
3. See LiteLLM docs: https://docs.litellm.ai/docs/providers

### Error: "Insufficient funds"

1. Add credits to your provider account
2. Set a budget alert
3. Use cheaper models (gpt-4o-mini, claude-haiku)

---

## Summary

| Component | Purpose | Status |
|-----------|---------|--------|
| Model Registry | Stores metadata | ✅ Configured (7 models) |
| LiteLLM Gateway | Invokes models | ⚠️ Needs API keys |
| API Keys | Authenticates with providers | ⚠️ Add to .env file |
| Vault (optional) | Secure key storage | 🔧 For production |

**Next Steps**:
1. ✅ Add API keys to `.env` file
2. ✅ Update `docker-compose.yml` to pass keys to containers
3. ✅ Restart services
4. ✅ Test with verification scripts above

Once API keys are configured, the Dynamic Model Router will be able to actually invoke the registered models!
