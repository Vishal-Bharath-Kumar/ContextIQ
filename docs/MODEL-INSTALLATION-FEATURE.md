# Model Installation Feature - Implementation Summary

## Overview

Implemented a comprehensive model installation system in ContextIQ that allows users to install and configure AI models directly from the UI. The system supports both API-based models (OpenAI, Anthropic, Google, Azure OpenAI, Hugging Face) and local Ollama models.

## Features Implemented

### 1. **API-Based Model Installation** (OpenAI, Anthropic, Google, Azure, etc.)
   - User-friendly wizard interface for entering API credentials
   - Secure credential storage in HashiCorp Vault
   - Auto-detection of model capabilities based on model ID
   - Auto-detection of latency tier (fast/medium/slow)
   - Support for custom API base URLs
   - Azure OpenAI specific fields (deployment name, API version)
   - Model metadata presets for common models

### 2. **Ollama Model Installation**
   - One-click installation from popular Ollama models list
   - Auto-pull functionality to download models if not available
   - Display of currently downloaded Ollama models
   - Auto-detection of context window based on model name
   - Zero-cost model registration (Ollama is free)

### 3. **Enhanced UI/UX**
   - Separate "Install Model" and "Register Model" workflows
   - Install Model: For new models requiring credentials or download
   - Register Model: For manually registering already-configured models
   - Real-time validation with helpful error messages
   - Success messages with auto-navigation
   - Model preset suggestions for common models

---

## Backend Implementation

### New Files Created

#### 1. **`src/model_registry/schemas/model_installation.py`**
   - `ModelProviderType`: Enum for provider types (OpenAI, Anthropic, Google, Azure, Ollama, etc.)
   - `ModelInstallationRequest`: Request schema for installing models
   - `OllamaModelInfo`: Schema for Ollama model information
   - `OllamaPullRequest` / `OllamaPullResponse`: Schemas for Ollama pull operations
   - `ModelInstallationResponse`: Unified response schema

#### 2. **`src/model_registry/services/ollama_service.py`**
   - `OllamaService.list_models()`: List all downloaded Ollama models
   - `OllamaService.pull_model()`: Pull/download an Ollama model
   - `OllamaService.get_model_info()`: Get detailed model information
   - `OllamaService.check_model_exists()`: Verify if model is available
   - `OllamaService.estimate_context_window()`: Auto-detect context window by model name

#### 3. **`src/model_registry/services/model_credential_service.py`**
   - `ModelCredentialService.store_credentials()`: Securely store API keys in Vault
   - `ModelCredentialService.retrieve_credentials()`: Retrieve credentials from Vault
   - `ModelCredentialService.delete_credentials()`: Remove stored credentials
   - Integration with HashiCorp Vault (AppRole auth)

### Modified Files

#### 1. **`src/model_registry/services/model_registry_service.py`**
   - Added `install_model()`: Main installation orchestration method
   - Added `_install_ollama_model()`: Ollama-specific installation logic
   - Added `_install_api_model()`: API provider installation logic
   - Added `_detect_capabilities()`: Auto-detect model capabilities
   - Added `_detect_latency_tier()`: Auto-detect latency tier

#### 2. **`src/model_registry/routers/model_router.py`**
   - `POST /v1/models/install`: Install a model with credentials
   - `GET /v1/models/ollama`: List downloaded Ollama models
   - `POST /v1/models/ollama/pull`: Pull an Ollama model
   - Updated imports to include new schemas

---

## Frontend Implementation

### New Files Created

#### 1. **`frontend/admin-portal/src/schemas/installModelSchema.ts`**
   - Discriminated union schema for different provider types
   - Separate validation for Ollama vs API-based providers
   - Azure OpenAI specific validation
   - Provider type enum

#### 2. **`frontend/admin-portal/src/pages/models/InstallModelPage.tsx`**
   - Multi-step wizard interface
   - Provider selection dropdown
   - Dynamic form fields based on provider type
   - Popular Ollama models quick-select grid
   - Model preset auto-fill for common models
   - Real-time validation and error handling
   - Success/error message display
   - Auto-navigation on success

### Modified Files

#### 1. **`frontend/admin-portal/src/services/modelService.ts`**
   - `useOllamaModels()`: Query hook for Ollama models
   - `useInstallModel()`: Mutation hook for model installation
   - `usePullOllamaModel()`: Mutation hook for pulling Ollama models
   - TypeScript interfaces for new API responses

#### 2. **`frontend/admin-portal/src/routes/index.tsx`**
   - Added `/models/install` route
   - Imported `InstallModelPage` component

#### 3. **`frontend/admin-portal/src/pages/models/ModelListPage.tsx`**
   - Added "Install Model" button (primary)
   - Moved "Register Model" to secondary button
   - Improved button organization

---

## API Endpoints

### New Endpoints

```typescript
POST /v1/models/install
```
- **Purpose**: Install a new model with credentials (API-based or Ollama)
- **Request Body**: `ModelInstallationRequest`
- **Response**: `ModelInstallationResponse`
- **Auth**: Requires `PLATFORM_ENGINEER` or `ADMIN` role

```typescript
GET /v1/models/ollama
```
- **Purpose**: List all downloaded Ollama models
- **Response**: `OllamaModelInfo[]`
- **Auth**: Requires `PLATFORM_ENGINEER` or `ADMIN` role

```typescript
POST /v1/models/ollama/pull
```
- **Purpose**: Pull/download an Ollama model
- **Request Body**: `OllamaPullRequest`
- **Response**: `OllamaPullResponse`
- **Auth**: Requires `PLATFORM_ENGINEER` or `ADMIN` role

---

## Security Features

1. **Vault Integration**
   - API keys stored in HashiCorp Vault (`secret/models/{provider_type}/{model_id}`)
   - AppRole authentication for Vault access
   - Graceful degradation for local development without Vault

2. **Role-Based Access Control**
   - All endpoints protected by `require_manage_models` dependency
   - Only PLATFORM_ENGINEER and ADMIN roles can install models

3. **Audit Logging**
   - All model installation actions logged to admin audit log
   - Tracks model registration events
   - Records Ollama pull operations

---

## Auto-Detection Features

### Model Capabilities Auto-Detection
```python
# Based on model ID patterns
"code", "coder", "codex" → CODE capability
"vision", "gpt-4o", "claude-3" → VISION capability
OpenAI/Anthropic/Google → FUNCTION_CALL capability
"embed" → EMBEDDING capability (exclusive)
```

### Latency Tier Auto-Detection
```python
"mini", "haiku", "flash", "turbo" → FAST
"o1", "reasoning", "think" → SLOW
Default → MEDIUM
```

### Context Window Estimation (Ollama)
```python
llama3.2, llama3.1 → 128,000 tokens
mistral, mixtral → 32,768 tokens
phi3 → 128,000 tokens
deepseek-coder, codellama → 16,384 tokens
Default → 4,096 tokens
```

---

## User Workflows

### Installing an OpenAI Model

1. Navigate to Models → "Install Model"
2. Select "OpenAI" as provider
3. Enter API key (e.g., `sk-proj-...`)
4. Enter model ID (e.g., `gpt-4o-mini`)
5. Context window and cost auto-filled from presets
6. Click "Install Model"
7. Model registered and credentials stored in Vault

### Installing an Ollama Model

1. Navigate to Models → "Install Model"
2. Select "Ollama" as provider
3. Click on a popular model (e.g., "llama3.2") or enter custom name
4. Enable "Automatically download model if not available"
5. Click "Install Model"
6. System pulls model if needed and registers it
7. Model available at $0.00 cost

### Installing Azure OpenAI

1. Navigate to Models → "Install Model"
2. Select "Azure OpenAI" as provider
3. Enter API key, API base URL, API version, and deployment name
4. Enter model ID and context window
5. Click "Install Model"
6. Credentials stored in Vault with Azure-specific config

---

## Environment Variables

```bash
# Ollama Configuration
OLLAMA_BASE_URL=http://host.docker.internal:11434

# Vault Configuration (for credential storage)
VAULT_ADDR=http://vault:8200
VAULT_TOKEN=your-vault-token  # OR
VAULT_ROLE_ID=your-role-id
VAULT_SECRET_ID=your-secret-id
```

---

## Model Presets (Auto-Fill)

The system includes presets for common models to simplify configuration:

| Model ID | Context Window | Cost/1K Tokens |
|----------|---------------|----------------|
| gpt-4o | 128,000 | $0.005 |
| gpt-4o-mini | 128,000 | $0.00015 |
| claude-3-opus-20240229 | 200,000 | $0.015 |
| claude-3-sonnet-20240229 | 200,000 | $0.003 |
| claude-3-haiku-20240307 | 200,000 | $0.00025 |
| gemini-pro | 32,768 | $0.00025 |

---

## Testing

### Backend Testing
```bash
# Test Ollama list
curl -X GET http://localhost:8000/v1/models/ollama \
  -H "Authorization: Bearer $TOKEN"

# Test Ollama pull
curl -X POST http://localhost:8000/v1/models/ollama/pull \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "llama3.2"}'

# Test model installation (OpenAI)
curl -X POST http://localhost:8000/v1/models/install \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_type": "openai",
    "model_id": "gpt-4o-mini",
    "display_name": "GPT-4o Mini",
    "api_key": "sk-...",
    "context_window": 128000,
    "cost_per_1k_tokens": 0.00015
  }'

# Test model installation (Ollama)
curl -X POST http://localhost:8000/v1/models/install \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_type": "ollama",
    "model_id": "ollama/llama3.2",
    "display_name": "Llama 3.2",
    "ollama_model_name": "llama3.2",
    "auto_pull": true
  }'
```

### Frontend Testing
1. Open admin portal: http://localhost:3000
2. Login with PLATFORM_ENGINEER or ADMIN role
3. Navigate to Models
4. Click "Install Model"
5. Test each provider type (OpenAI, Anthropic, Ollama, etc.)
6. Verify validation errors for missing fields
7. Verify success messages and auto-navigation

---

## Future Enhancements

1. **Model Testing Before Registration**
   - Test API connectivity before storing credentials
   - Validate API keys work with test request

2. **Model Versioning**
   - Track model versions
   - Support multiple versions of same model

3. **Credential Rotation**
   - UI for updating API keys
   - Automatic expiration warnings

4. **Ollama Model Catalog**
   - Fetch available models from Ollama registry
   - Show model descriptions and sizes

5. **Batch Installation**
   - Install multiple models at once
   - Import from configuration file

---

## Files Modified/Created Summary

### Backend (Python)
- ✅ Created: `src/model_registry/schemas/model_installation.py`
- ✅ Created: `src/model_registry/services/ollama_service.py`
- ✅ Created: `src/model_registry/services/model_credential_service.py`
- ✅ Modified: `src/model_registry/services/model_registry_service.py`
- ✅ Modified: `src/model_registry/routers/model_router.py`

### Frontend (TypeScript/React)
- ✅ Created: `frontend/admin-portal/src/schemas/installModelSchema.ts`
- ✅ Created: `frontend/admin-portal/src/pages/models/InstallModelPage.tsx`
- ✅ Modified: `frontend/admin-portal/src/services/modelService.ts`
- ✅ Modified: `frontend/admin-portal/src/routes/index.tsx`
- ✅ Modified: `frontend/admin-portal/src/pages/models/ModelListPage.tsx`

---

## Deployment Checklist

- [ ] Ensure Vault is configured and accessible
- [ ] Set `OLLAMA_BASE_URL` environment variable
- [ ] Set Vault credentials (`VAULT_ROLE_ID`, `VAULT_SECRET_ID`)
- [ ] Rebuild API container: `docker compose build api`
- [ ] Rebuild frontend: `cd frontend/admin-portal && npm run build`
- [ ] Restart services: `docker compose up -d`
- [ ] Verify Ollama is running and accessible
- [ ] Test model installation workflow end-to-end

---

## Success Criteria

✅ Users can install API-based models with credentials from the UI
✅ API keys are securely stored in Vault
✅ Users can install Ollama models with one-click
✅ Ollama models can be auto-pulled if not available
✅ Model capabilities and latency tiers are auto-detected
✅ Validation prevents invalid configurations
✅ Audit logs track all installation activities
✅ UI is intuitive with helpful guidance and presets

---

## Support

For issues or questions:
- Check backend logs: `docker compose logs api`
- Check frontend console for errors
- Verify Vault connectivity
- Verify Ollama is running: `curl http://localhost:11434/api/tags`

