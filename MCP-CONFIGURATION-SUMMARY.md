# ContextIQ MCP Configuration Summary

## What Was Created

Complete MCP (Model Context Protocol) configuration for ContextIQ to connect with various AI assistants across different repositories.

## Files Created

### Configuration Files
```
mcp-client-config.json              # Base MCP client configuration template
.env.mcp.template                   # Environment variable template
MCP-QUICKSTART.md                   # Quick start guide (5 minutes)
```

### Documentation
```
docs/config/
├── README.md                       # Configuration overview
├── mcp-client-setup.md            # Comprehensive setup guide (all assistants)
├── mcp-claude-desktop.md          # Claude Desktop configuration
├── mcp-cursor.md                  # Cursor IDE configuration  
├── mcp-vscode.md                  # VS Code / GitHub Copilot configuration
├── mcp-windsurf.md                # Windsurf IDE configuration
├── mcp-continue.md                # Continue extension configuration
└── .gitignore                     # Prevent committing secrets
```

### Updates
```
.vscode/mcp.json                   # Added ContextIQ server example
```

## Quick Start

### 1. Start ContextIQ
```bash
docker compose up -d
```

### 2. Set Authentication Token
```bash
export CONTEXTIQ_TOKEN="your-jwt-token-here"
```

### 3. Configure Your AI Assistant

**Claude Desktop**: `~/Library/Application Support/Claude/claude_desktop_config.json`
```json
{
  "mcpServers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

**Cursor**: `~/.cursor/mcp.json`
```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

**VS Code**: `.vscode/mcp.json`
```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

### 4. Restart Your AI Assistant

Restart the AI assistant completely for changes to take effect.

## Available Transports

### Server-Sent Events (SSE) - Recommended
- **Endpoint**: `http://localhost:8080/mcp/sse`
- **Protocol**: HTTP with streaming
- **Best for**: Most AI assistants

### WebSocket
- **Endpoint**: `ws://localhost:8080/mcp/ws`
- **Protocol**: WebSocket persistent connection
- **Best for**: Real-time bidirectional communication

## Multi-Repository Support

Configure separate connections for different repositories:

```json
{
  "contextiq-frontend": {
    "type": "http",
    "url": "http://localhost:8080/mcp/sse",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
      "X-Repository": "frontend-app"
    }
  },
  "contextiq-backend": {
    "type": "http",
    "url": "http://localhost:8080/mcp/sse",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
      "X-Repository": "backend-api"
    }
  }
}
```

## Available MCP Tools

Once connected, AI assistants can invoke:

### Search & Retrieval
- `semantic_search` - Search across knowledge sources
- `hybrid_search` - Combined semantic + keyword
- `retrieve_context` - Get specific documents

### Knowledge Sources
- `list_sources` - List all sources
- `sync_source` - Trigger sync
- `get_source_status` - Check status

### Agent Operations
- `clarification_reply` - Provide context
- `execute_workflow` - Run workflows
- `get_workflow_status` - Check execution

### Analysis
- `analyze_code` - Security & quality analysis
- `extract_entities` - Extract structured data
- `check_policy_compliance` - Verify policies

## Environment Setup

### Create .env file
```bash
cp .env.mcp.template .env
# Edit .env with your values
nano .env
```

### Add to .gitignore
```bash
echo .env >> .gitignore
```

### Set in shell profile
```bash
# macOS/Linux - Add to ~/.zshrc or ~/.bashrc
export CONTEXTIQ_TOKEN="your-jwt-token-here"
export CONTEXTIQ_PROD_TOKEN="production-token"

# Reload
source ~/.zshrc
```

## Testing

### Health Check
```bash
curl http://localhost:8080/health
```

### MCP Endpoint
```bash
curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
     http://localhost:8080/mcp/sse
```

### List Tools
```bash
curl -X POST \
     -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
     http://localhost:8080/mcp/sse
```

## Production Configuration

### Use HTTPS
```json
{
  "contextiq-prod": {
    "type": "http",
    "url": "https://contextiq.example.com/mcp/sse",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_PROD_TOKEN}"
    }
  }
}
```

### Separate Tokens
- Dev: `CONTEXTIQ_TOKEN`
- Staging: `CONTEXTIQ_STAGING_TOKEN`
- Production: `CONTEXTIQ_PROD_TOKEN`

### Configure Ingress
See `k8s/ingress-nginx/` for Kubernetes ingress setup.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│           AI Assistants (MCP Clients)                   │
│  Claude | Cursor | VS Code | Windsurf | Continue        │
└────────────────────┬────────────────────────────────────┘
                     │ MCP over HTTP/WebSocket
                     │
┌────────────────────▼────────────────────────────────────┐
│              ContextIQ MCP Gateway                      │
│         :8080/mcp/sse  |  :8080/mcp/ws                  │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┬──────────────┐
        │                         │              │
┌───────▼────────┐    ┌──────────▼─────┐   ┌───▼────────┐
│ Agent Worker   │    │ Indexing       │   │ Knowledge  │
│ (LangGraph)    │    │ Service        │   │ Sources    │
└────────────────┘    └────────────────┘   └────────────┘
```

## Security Best Practices

1. ✅ **Never commit tokens** - Use environment variables
2. ✅ **Use HTTPS in production** - TLS encryption
3. ✅ **Rotate tokens regularly** - Periodic refresh
4. ✅ **Separate environments** - Different tokens per env
5. ✅ **Monitor access** - Enable audit logging
6. ✅ **Least privilege** - Minimal permissions

## Troubleshooting

### Connection Refused
```bash
docker compose ps                    # Check services
docker compose logs gateway          # View logs
curl http://localhost:8080/health    # Test health
```

### Authentication Failed
```bash
echo $CONTEXTIQ_TOKEN                # Verify token
# Check token expiry and permissions
```

### Tools Not Appearing
- Restart AI assistant completely
- Verify JSON syntax: `cat config.json | jq .`
- Check AI assistant logs for errors

## Documentation Index

### Getting Started
- [MCP Quick Start](../../MCP-QUICKSTART.md) - 5-minute setup
- [Configuration Overview](./README.md) - This directory

### AI Assistant Guides
- [Comprehensive Setup](./mcp-client-setup.md) - All assistants
- [Claude Desktop](./mcp-claude-desktop.md) - Claude specific
- [Cursor](./mcp-cursor.md) - Cursor IDE
- [VS Code](./mcp-vscode.md) - GitHub Copilot
- [Windsurf](./mcp-windsurf.md) - Windsurf IDE
- [Continue](./mcp-continue.md) - Continue extension

### Reference
- [MCP Response Schemas](../api/mcp-response-schemas.md)
- [BRD - MCP Gateway](../BRD.md#15-enterprise-mcp-gateway)
- [Connector SDK](../connector-sdk.md)

## Next Steps

### 1. Add Knowledge Sources
Configure GitHub, Confluence, or other connectors:
```bash
# See docs/connector-sdk.md
```

### 2. Set Up Multi-Repository
Configure separate MCP connections for different repos.

### 3. Production Deployment
- Configure HTTPS/TLS
- Set up load balancing
- Enable monitoring

### 4. Customize Tools
Extend ContextIQ with custom enterprise tools.

### 5. Monitor Usage
- Track MCP request metrics
- Monitor tool invocation rates
- Set up alerting

## Support

- **Quick Start**: See [MCP-QUICKSTART.md](../../MCP-QUICKSTART.md)
- **Logs**: `docker compose logs -f gateway`
- **Health**: `curl http://localhost:8080/health`
- **Docs**: See `docs/config/` directory

## Contributing

When adding new AI assistant support:
1. Create `mcp-{assistant}.md` in `docs/config/`
2. Follow existing structure
3. Include setup, examples, troubleshooting
4. Update `docs/config/README.md`
5. Test configuration before committing

## License

See [LICENSE](../../LICENSE) file in project root.

---

**ContextIQ MCP Configuration - Complete** ✅

All AI assistants can now connect to ContextIQ and access enterprise knowledge across repositories!
