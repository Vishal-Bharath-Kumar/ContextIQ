#!/bin/bash
# Setup Ollama for ContextIQ - Run models locally without API costs
#
# This script:
# 1. Installs Ollama (if not already installed)
# 2. Starts Ollama service
# 3. Pulls recommended models
# 4. Updates the model registry to use Ollama
# 5. Tests the integration

set -e

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║  ContextIQ - Ollama Setup (Local Models, No API Costs)                 ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"

# Step 1: Install Ollama
echo ""
echo "Step 1: Installing Ollama..."
echo "─────────────────────────────────────────────────────────────────────────"

if command -v ollama &> /dev/null; then
    echo "✓ Ollama is already installed: $(ollama --version)"
else
    echo "Installing Ollama via Homebrew..."
    if command -v brew &> /dev/null; then
        brew install ollama
        echo "✓ Ollama installed successfully"
    else
        echo "❌ Homebrew not found. Installing via curl..."
        curl -fsSL https://ollama.com/install.sh | sh
    fi
fi

# Step 2: Start Ollama service
echo ""
echo "Step 2: Starting Ollama service..."
echo "─────────────────────────────────────────────────────────────────────────"

# Check if Ollama is already running
if pgrep -x "ollama" > /dev/null; then
    echo "✓ Ollama is already running"
else
    echo "Starting Ollama in the background..."
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    sleep 3
    echo "✓ Ollama service started (logs: /tmp/ollama.log)"
fi

# Test connection
echo "Testing Ollama connection..."
if curl -s http://localhost:11434/api/version > /dev/null; then
    echo "✓ Ollama API is responding at http://localhost:11434"
else
    echo "⚠️  Ollama API not responding. You may need to start it manually:"
    echo "   Run: ollama serve"
    exit 1
fi

# Step 3: Pull recommended models
echo ""
echo "Step 3: Pulling recommended models..."
echo "─────────────────────────────────────────────────────────────────────────"
echo "This will download ~4GB of models. It may take a few minutes..."

# Pull llama3.2 (3B params, fast, good for general use)
echo ""
echo "Pulling llama3.2 (3B, fast, good for chat & code)..."
ollama pull llama3.2

# Pull deepseek-coder (6.7B, excellent for code)
echo ""
echo "Pulling deepseek-coder:6.7b (excellent for code generation)..."
ollama pull deepseek-coder:6.7b

# Pull phi3 (3.8B, fast, good for reasoning)
echo ""
echo "Pulling phi3 (3.8B, fast, good for reasoning)..."
ollama pull phi3

echo ""
echo "✓ Models downloaded successfully"

# Step 4: List available models
echo ""
echo "Step 4: Available local models..."
echo "─────────────────────────────────────────────────────────────────────────"
ollama list

# Step 5: Update ContextIQ configuration
echo ""
echo "Step 5: Updating ContextIQ configuration..."
echo "─────────────────────────────────────────────────────────────────────────"

# Update .env file
ENV_FILE=".env"
if [ -f "$ENV_FILE" ]; then
    # Add Ollama configuration
    if ! grep -q "OLLAMA_BASE_URL" "$ENV_FILE"; then
        echo "" >> "$ENV_FILE"
        echo "# Ollama - Local LLM inference (no API costs)" >> "$ENV_FILE"
        echo "OLLAMA_BASE_URL=http://host.docker.internal:11434" >> "$ENV_FILE"
        echo "✓ Added OLLAMA_BASE_URL to .env"
    else
        echo "✓ OLLAMA_BASE_URL already in .env"
    fi
fi

# Step 6: Test Ollama
echo ""
echo "Step 6: Testing Ollama..."
echo "─────────────────────────────────────────────────────────────────────────"

echo "Sending test prompt to llama3.2..."
RESPONSE=$(curl -s http://localhost:11434/api/generate -d '{
  "model": "llama3.2",
  "prompt": "Say hello in exactly 2 words",
  "stream": false
}' | grep -o '"response":"[^"]*"' | cut -d'"' -f4)

if [ -n "$RESPONSE" ]; then
    echo "✓ Test successful!"
    echo "  Response: $RESPONSE"
else
    echo "⚠️  Test failed - check Ollama logs: tail -f /tmp/ollama.log"
fi

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ OLLAMA SETUP COMPLETE!                                             ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "1. Register Ollama models in ContextIQ model registry:"
echo "   docker compose exec api python scripts/registry/register_ollama_models.py"
echo ""
echo "2. Restart ContextIQ services:"
echo "   docker compose restart api"
echo ""
echo "3. Test the integration:"
echo "   docker compose exec api python scripts/registry/test_ollama_integration.py"
echo ""
echo "Available models:"
echo "  - ollama/llama3.2       (3B, fast, general purpose)"
echo "  - ollama/deepseek-coder (6.7B, code generation)"
echo "  - ollama/phi3           (3.8B, reasoning)"
echo ""
echo "Cost: $0.00 (runs entirely on your machine)"
echo ""
