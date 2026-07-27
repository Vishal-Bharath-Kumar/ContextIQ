# ContextIQ MCP Quick Start Guide

Get up and running with ContextIQ's Model Context Protocol server in 5 minutes.

## Prerequisites

- Docker & Docker Compose installed
- AI assistant installed (Claude Desktop, Cursor, VS Code with Copilot, etc.)

## Step 1: Start ContextIQ

```bash
# Clone the repository (if not already done)
cd /path/to/ContextIQ

# Start all services
docker compose up -d

# Verify services are running
docker compose ps
```

Expected output should show services running:
- `postgres` - Database
- `redis` - Cache
- `gateway` - MCP Gateway (port 8080)
- `api` - API service
- `indexing` - Indexing service

## Step 2: Get Authentication Token

### Option A: Local Development (No Auth)
For local development, you can disable JWT authentication:

```bash
export CONTEXTIQ_JWT_AUTH_ENABLED=false
docker compose restart gateway
```

### Option B: JWT Token (Production)
Obtain a JWT token from ContextIQ authentication service:

```bash
# Set your token
export CONTEXTIQ_TOKEN="your-jwt-token-here"

# Verify token is set
echo $CONTEXTIQ_TOKEN
```

Add to your shell profile for persistence:
```bash
# macOS/Linux - Add to ~/.zshrc or ~/.bashrc
echo 'export CONTEXTIQ_TOKEN="your-jwt-token"' >> ~/.zshrc
source ~/.zshrc

# Windows PowerShell - Add to $PROFILE
echo '$env:CONTEXTIQ_TOKEN = "your-jwt-token"' >> $PROFILE
. $PROFILE
```

## Step 3: Test MCP Connection

```bash
# Test health endpoint
curl http://localhost:8080/health

# Test MCP endpoint (with auth)
curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
     http://localhost:8080/mcp/sse

# List available tools
curl -X POST \
     -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
     http://localhost:8080/mcp/sse
```

## Step 4: Configure Your AI Assistant

### Claude Desktop

**File**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

Restart Claude Desktop after saving.

### Cursor

**File**: `~/.cursor/mcp.json`

```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

Restart Cursor after saving.

### VS Code / GitHub Copilot

**File**: `.vscode/mcp.json` (in your workspace)

```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

Reload VS Code window: `Cmd+Shift+P` → "Developer: Reload Window"

## Step 5: Test in Your AI Assistant

### Claude Desktop
```
Can you list the available ContextIQ tools?

Search ContextIQ for authentication implementations
```

### Cursor
```
@contextiq semantic_search authentication patterns

@contextiq list_sources
```

### VS Code Copilot
```
@workspace using ContextIQ, find database migration examples

Search ContextIQ for API documentation
```

## Quick Troubleshooting

### ContextIQ Not Running
```bash
# Check service status
docker compose ps

# View logs
docker compose logs gateway

# Restart services
docker compose restart
```

### Connection Refused
```bash
# Verify port 8080 is accessible
curl http://localhost:8080/health

# Check gateway logs
docker compose logs -f gateway
```

### Authentication Failed
```bash
# Verify token is set
echo $CONTEXTIQ_TOKEN

# For local dev, disable auth
export CONTEXTIQ_JWT_AUTH_ENABLED=false
docker compose restart gateway
```

### Tools Not Appearing
- Restart your AI assistant completely
- Verify JSON syntax in config file: `cat ~/.cursor/mcp.json | jq .`
- Check AI assistant logs for errors

## Available MCP Tools

Once connected, you can use:

### Search & Retrieval
- `semantic_search` - Search across knowledge sources
- `hybrid_search` - Combined semantic + keyword search
- `retrieve_context` - Get specific documents

### Knowledge Management
- `list_sources` - List all knowledge sources
- `sync_source` - Trigger sync
- `get_source_status` - Check sync status

### Agent Operations
- `clarification_reply` - Provide context to agents
- `execute_workflow` - Run multi-agent workflows

### Analysis
- `analyze_code` - Code quality and security analysis
- `extract_entities` - Extract structured data

## Next Steps

1. **Add Knowledge Sources**: Configure GitHub, Confluence, or other sources
   ```bash
   # See docs/connector-sdk.md for details
   ```

2. **Set Up Multi-Repository**: Configure separate MCP connections for different repos
   ```bash
   # See docs/config/mcp-client-setup.md
   ```

3. **Production Deployment**: Set up HTTPS and proper authentication
   ```bash
   # See docs/config/mcp-client-setup.md#production-deployment
   ```

4. **Monitor Usage**: Enable observability and audit logging
   ```bash
   # See docs/observability/
   ```

## Documentation

- [Comprehensive Setup Guide](docs/config/mcp-client-setup.md)
- [Claude Desktop Config](docs/config/mcp-claude-desktop.md)
- [Cursor Config](docs/config/mcp-cursor.md)
- [VS Code Config](docs/config/mcp-vscode.md)
- [API Documentation](docs/api/)
- [Architecture](docs/architecture/)

## Environment Template

Copy and customize the environment template:

```bash
cp .env.mcp.template .env
# Edit .env with your values
nano .env

# Ensure .env is in .gitignore
echo .env >> .gitignore
```

## Support

- **Logs**: `docker compose logs -f gateway`
- **Health Check**: `curl http://localhost:8080/health`
- **Documentation**: See `docs/` directory
- **Issues**: Check [troubleshooting guide](docs/config/mcp-client-setup.md#troubleshooting)

## Security Reminder

⚠️ **Never commit authentication tokens to version control!**

```bash
# Always add .env to .gitignore
echo .env >> .gitignore

# Use environment variables for tokens
export CONTEXTIQ_TOKEN="your-token"

# Rotate tokens regularly
```

---

**Ready to use ContextIQ with your AI assistant!** 🚀

For detailed configuration options and advanced features, see the [full documentation](docs/config/).
