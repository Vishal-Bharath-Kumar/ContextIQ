# Quick Start: Testing Model Installation Feature

## Prerequisites

1. **ContextIQ running**
   ```bash
   docker compose up -d
   ```

2. **Ollama running** (for Ollama model installation)
   ```bash
   # Check Ollama status
   curl http://localhost:11434/api/tags
   ```

3. **Admin credentials** (PLATFORM_ENGINEER or ADMIN role)

---

## Test 1: Install an Ollama Model (5 min)

### Step 1: Access Admin Portal
```
http://localhost:3000
```
Login with your admin credentials.

### Step 2: Navigate to Models
1. Click "Models" in the sidebar
2. Click the "Install Model" button (blue, with download icon)

### Step 3: Install Llama 3.2
1. Provider Type: Select "Ollama"
2. Click on "llama3.2" in the popular models list (or enter manually)
3. Enable "Automatically download model if not available"
4. Click "Install Model"

### Expected Result
✅ Success message: "Ollama model 'llama3.2' installed and registered successfully"
✅ Auto-redirect to Models list
✅ New model visible in the table: `ollama/llama3.2` with $0.00 cost

### Verify
```bash
# Check model is in database
docker compose exec api python -c "
from src.data.database import primary_session_factory
from sqlalchemy import text
import asyncio

async def main():
    async with primary_session_factory()() as session:
        result = await session.execute(
            text(\"SELECT model_id, provider, cost_per_1k_tokens FROM model_definitions WHERE provider = 'ollama'\")
        )
        for row in result:
            print(f'{row[0]} | {row[1]} | \${row[2]}/1k tokens')

asyncio.run(main())
"
```

---

## Test 2: Install OpenAI GPT-4o-mini (3 min)

### Prerequisites
- OpenAI API key (get from https://platform.openai.com/api-keys)

### Step 1: Navigate to Install Model
Models → Install Model

### Step 2: Configure OpenAI Model
1. Provider Type: **OpenAI**
2. API Key: `sk-proj-...` (your OpenAI API key)
3. Model ID: `gpt-4o-mini`
4. Display Name: `GPT-4o Mini`
5. Context Window: Auto-filled to `128000`
6. Cost per 1K Tokens: Auto-filled to `0.00015`

### Step 3: Install
Click "Install Model"

### Expected Result
✅ Success message: "Model 'gpt-4o-mini' installed and registered successfully"
✅ Model appears in list with correct metadata
✅ API key stored in Vault (not visible in UI)

### Verify Vault Storage
```bash
# Check Vault has the credential (requires Vault access)
docker compose exec api python -c "
from src.model_registry.services.model_credential_service import ModelCredentialService
import asyncio

async def main():
    service = ModelCredentialService()
    creds = await service.retrieve_credentials('gpt-4o-mini', 'openai')
    if creds:
        print('✓ Credentials stored in Vault')
        print(f'  API key starts with: {creds[\"api_key\"][:10]}...')
    else:
        print('⚠ Credentials not found (Vault may not be configured)')

asyncio.run(main())
"
```

---

## Test 3: Install Anthropic Claude (3 min)

### Prerequisites
- Anthropic API key (get from https://console.anthropic.com/)

### Step 1: Install Claude Haiku
1. Provider Type: **Anthropic**
2. API Key: `sk-ant-...`
3. Model ID: `claude-3-haiku-20240307`
4. Display Name: `Claude 3 Haiku`
5. Context Window: Auto-filled to `200000`
6. Cost: Auto-filled to `0.00025`

### Expected Result
✅ Model installed successfully
✅ Credentials stored securely

---

## Test 4: Install Azure OpenAI (5 min)

### Prerequisites
- Azure OpenAI resource
- API key, endpoint, deployment name

### Step 1: Configure Azure
1. Provider Type: **Azure OpenAI**
2. API Key: Your Azure key
3. API Base URL: `https://your-resource.openai.azure.com`
4. API Version: `2024-02-15-preview`
5. Deployment Name: Your deployment name
6. Model ID: `azure/gpt-4o`
7. Display Name: `Azure GPT-4o`
8. Context Window: `128000`
9. Cost: `0.005`

### Expected Result
✅ All Azure-specific fields stored
✅ Model registered with Azure provider

---

## Test 5: Pull Multiple Ollama Models (10 min)

Test pulling several popular Ollama models:

### Quick Install List
1. **llama3.2** (2GB) - Fast general-purpose
2. **phi3** (2GB) - Fast reasoning
3. **mistral** (4GB) - Excellent 7B model
4. **deepseek-coder:6.7b** (3GB) - Code generation

### Batch Test Script
```bash
# Pull models via API
for model in "llama3.2" "phi3" "mistral" "deepseek-coder:6.7b"; do
  echo "Installing $model..."
  curl -X POST http://localhost:8000/v1/models/install \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"provider_type\": \"ollama\",
      \"model_id\": \"ollama/$model\",
      \"display_name\": \"$model\",
      \"ollama_model_name\": \"$model\",
      \"auto_pull\": true
    }"
  echo ""
done
```

---

## Test 6: Validation Testing

### Test Invalid API Key Format
1. Provider: OpenAI
2. API Key: `invalid-key` (too short)
3. Expected: Validation error before submission

### Test Missing Required Fields
1. Provider: Azure OpenAI
2. Leave deployment_name empty
3. Expected: "Deployment name is required" error

### Test Ollama Without Auto-Pull
1. Provider: Ollama
2. Model: `nonexistent-model:latest`
3. Disable auto-pull
4. Expected: Error "Ollama model not found. Enable auto_pull to download it."

---

## Test 7: UI/UX Testing

### Test Auto-Fill
1. Select OpenAI
2. Enter model ID: `gpt-4o-mini`
3. Verify: Context window and cost auto-populate

### Test Popular Models Grid
1. Select Ollama
2. Click any popular model box
3. Verify: All fields auto-populate

### Test Provider Switching
1. Select OpenAI (shows API key field)
2. Switch to Ollama (API key field hidden)
3. Switch to Azure (shows Azure-specific fields)
4. Verify: Forms update correctly

---

## Test 8: List Ollama Models Endpoint

### Via API
```bash
curl -X GET http://localhost:8000/v1/models/ollama \
  -H "Authorization: Bearer YOUR_TOKEN" | jq
```

### Expected Response
```json
[
  {
    "name": "llama3.2:latest",
    "size": 2019393189,
    "digest": "a80c4f17...",
    "modified_at": "2024-01-28T..."
  }
]
```

---

## Test 9: End-to-End Workflow

### Complete User Journey
1. **Start**: User wants to use GPT-4o-mini
2. **Navigate**: Models → Install Model
3. **Configure**: Enter OpenAI details
4. **Install**: Click install button
5. **Verify**: Model appears in list
6. **Use**: Model now available in Model Router
7. **Audit**: Check audit log shows installation

### Verify Audit Log
```bash
docker compose exec api python -c "
from src.data.database import primary_session_factory
from sqlalchemy import text
import asyncio

async def main():
    async with primary_session_factory()() as session:
        result = await session.execute(
            text(\"SELECT action, resource_id, created_at FROM admin_audit_log WHERE resource_type = 'model' ORDER BY created_at DESC LIMIT 5\")
        )
        print('Recent model audit events:')
        for row in result:
            print(f'  {row[2]} | {row[0]} | {row[1]}')

asyncio.run(main())
"
```

---

## Troubleshooting

### Issue: "Failed to connect to Ollama"
**Solution:**
```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# If not running, start Ollama
ollama serve
```

### Issue: "Failed to store credentials in Vault"
**Solution:**
```bash
# Check Vault environment variables
docker compose exec api env | grep VAULT

# Test Vault connection
docker compose exec api python -c "
import hvac, os
client = hvac.Client(url=os.getenv('VAULT_ADDR', 'http://vault:8200'))
print('Vault sealed:', client.sys.is_sealed())
"
```

### Issue: Model doesn't appear in list after installation
**Solution:**
```bash
# Check Redis cache
docker compose exec api python -c "
from redis.asyncio import Redis
import asyncio

async def main():
    redis = Redis(host='redis', port=6379, db=0, decode_responses=True)
    exists = await redis.exists('model_registry:active_models')
    print('Cache exists:', bool(exists))
    if exists:
        await redis.delete('model_registry:active_models')
        print('Cache cleared')

asyncio.run(main())
"

# Refresh browser
```

---

## Success Checklist

After testing, verify:

- [ ] Ollama models install successfully
- [ ] OpenAI models install with API key
- [ ] Anthropic models install correctly
- [ ] Azure OpenAI handles all required fields
- [ ] API keys stored in Vault (if configured)
- [ ] Models appear in registry immediately
- [ ] Validation catches missing/invalid fields
- [ ] Auto-fill works for common models
- [ ] Popular Ollama models grid works
- [ ] Success messages display correctly
- [ ] Audit log records installations
- [ ] Navigation works smoothly

---

## Performance Benchmarks

### Ollama Model Pull Times (first install)
- llama3.2 (2GB): ~2-3 minutes
- phi3 (2GB): ~2-3 minutes
- mistral (4GB): ~4-6 minutes
- deepseek-coder (3.8GB): ~5-7 minutes

### API Model Installation (already have API key)
- OpenAI: <1 second
- Anthropic: <1 second
- Azure: <1 second

### UI Response Times
- Form load: <200ms
- Validation: <50ms
- Submit: <500ms (API models), 2-6 min (Ollama with pull)

---

## Next Steps

After successful testing:

1. ✅ Document any issues found
2. ✅ Test with production Vault instance
3. ✅ Test with real API keys
4. ✅ Train users on new workflow
5. ✅ Monitor audit logs
6. ✅ Set up alerts for failed installations

