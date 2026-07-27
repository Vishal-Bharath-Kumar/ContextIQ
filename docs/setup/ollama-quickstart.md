# Ollama Quick Start for ContextIQ

## What is Ollama?

Ollama lets you run AI models locally on your machine with **$0 cost**. No API keys, no rate limits, completely private.

## Quick Setup (3 Steps)

### Step 1: Install & Start Ollama

```bash
# Install (already done ✓)
brew install ollama

# Start Ollama service
ollama serve
```

Leave this running in a terminal.

### Step 2: Pull Models

Open a new terminal and download models:

```bash
# Fast, general-purpose (2GB)
ollama pull llama3.2

# Code generation (4GB)
ollama pull deepseek-coder:6.7b

# Optional: More powerful (5GB)
ollama pull llama3.1
```

### Step 3: Register in ContextIQ

```bash
# Register Ollama models in the model registry
docker compose exec api python /app/scripts/registry/register_ollama_models.py

# Restart API to load Ollama configuration
docker compose restart api

# Test the integration
docker compose exec api python /app/scripts/registry/test_ollama_integration.py
```

## Done! 🎉

Your ContextIQ now uses **free local models** instead of paid APIs.

---

## Benefits

✅ **$0 cost** - Runs entirely on your machine  
✅ **No rate limits** - Use as much as you want  
✅ **Full privacy** - Data never leaves your computer  
✅ **Works offline** - No internet required after download  
✅ **Fast** - Local inference, no network latency  

## Model Comparison

| Model | Size | Speed | Best For |
|-------|------|-------|----------|
| llama3.2 | 2GB | Fast | General chat, Q&A |
| deepseek-coder:6.7b | 4GB | Fast | Code generation |
| phi3 | 2GB | Very Fast | Quick tasks |
| llama3.1 | 5GB | Medium | Complex reasoning |

## Usage in ContextIQ

Once registered, the Dynamic Model Router will automatically use these local models:

```python
# The router sees these in the model registry:
- ollama/llama3.2        ($0.00, fast, general)
- ollama/deepseek-coder  ($0.00, fast, code)
- ollama/phi3            ($0.00, very fast)
- ollama/llama3.1        ($0.00, medium, powerful)
```

## Test Manually

```bash
# Test llama3.2
ollama run llama3.2 "Explain ContextIQ in 10 words"

# Test deepseek-coder
ollama run deepseek-coder:6.7b "Write a Python hello world"
```

## Troubleshooting

### "Connection refused"
```bash
# Start Ollama service
ollama serve
```

### "Model not found"
```bash
# Pull the model
ollama pull llama3.2
```

### "Slow performance"
- Ollama uses CPU by default
- On Apple Silicon Macs, it automatically uses GPU (very fast!)
- Smaller models (llama3.2, phi3) are faster

---

## Cost Savings

With Ollama, ContextIQ development costs:

| Before (OpenAI) | After (Ollama) |
|-----------------|----------------|
| ~$0.15/1M tokens | $0.00 |
| Rate limits | No limits |
| Quota errors | Never |
| **Monthly**: $50-200 | **$0** |

Perfect for development, testing, and demos! 🚀
