# ContextIQ MCP Configuration Examples

This directory contains configuration examples for connecting various AI assistants to ContextIQ's Model Context Protocol (MCP) server.

## Quick Start

1. **Start ContextIQ**
   ```bash
   docker compose up -d
   ```

2. **Get Authentication Token**
   ```bash
   # Obtain from your ContextIQ authentication service
   export CONTEXTIQ_TOKEN="your-jwt-token-here"
   ```

3. **Choose Your AI Assistant**
   - [Claude Desktop](./mcp-claude-desktop.md)
   - [Cursor](./mcp-cursor.md)
   - [VS Code / GitHub Copilot](./mcp-vscode.md)
   - [General Setup Guide](./mcp-client-setup.md)

## Available Configurations

### Main Configuration Files

| File | Description |
|------|-------------|
| [mcp-client-setup.md](./mcp-client-setup.md) | Comprehensive setup guide for all AI assistants |
| [mcp-claude-desktop.md](./mcp-claude-desktop.md) | Claude Desktop specific configuration |
| [mcp-cursor.md](./mcp-cursor.md) | Cursor IDE configuration |
| [mcp-vscode.md](./mcp-vscode.md) | VS Code / GitHub Copilot configuration |
| [mcp-windsurf.md](./mcp-windsurf.md) | Windsurf IDE configuration |
| [mcp-continue.md](./mcp-continue.md) | Continue extension configuration |

### Base Configuration Template

The [mcp-client-config.json](../../mcp-client-config.json) in the project root provides a template with:
- SSE (Server-Sent Events) transport
- WebSocket transport
- Local and production endpoints
- Multi-repository support examples

## ContextIQ MCP Endpoints

ContextIQ exposes two MCP transports:

### Server-Sent Events (Recommended)
```
http://localhost:8000/mcp/sse/
```
- Best for: Most AI assistants
- Protocol: HTTP with streaming responses
- Use case: Long-polling, one-way streaming

### WebSocket
```
ws://localhost:8000/mcp/ws
```
- Note: the default local Docker Compose stack publishes the SSE endpoint on the `api` service. Use SSE unless you separately expose the WebSocket route.
- Best for: Real-time bidirectional communication
- Protocol: WebSocket persistent connection
- Use case: Interactive agents, live updates

## Environment Variables

Set these in your environment:

```bash
# Required
export CONTEXTIQ_TOKEN="your-jwt-token-here"

# Optional - for production
export CONTEXTIQ_PROD_TOKEN="production-token"
export CONTEXTIQ_PROD_URL="https://contextiq.example.com"

# Optional - custom configuration
export CONTEXTIQ_MCP_TIMEOUT="30000"
export CONTEXTIQ_LOG_LEVEL="DEBUG"
```

## Multi-Repository Setup

ContextIQ supports working with multiple repositories simultaneously using custom headers:

```json
{
  "contextiq-repo-a": {
    "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
      "X-Repository": "frontend-app",
      "X-Project": "ecommerce",
      "X-Team": "platform"
    }
  }
}
```

### Custom Headers

| Header | Purpose | Example |
|--------|---------|---------|
| `X-Repository` | Target specific repository | `frontend-app` |
| `X-Project` | Filter by project | `ecommerce` |
| `X-Team` | Scope to team resources | `platform-team` |
| `X-Environment` | Target environment | `dev`, `staging`, `prod` |

## Available Tools

Once connected, AI assistants can invoke these ContextIQ tools:

### Retrieval & Search
- `semantic_search` - Semantic search across knowledge sources
- `hybrid_search` - Combined semantic + keyword search
- `retrieve_context` - Fetch specific documents or code
- `get_related_chunks` - Find related content

### Knowledge Source Management
- `list_sources` - List all knowledge sources
- `get_source_status` - Check sync status
- `sync_source` - Trigger manual sync
- `configure_source` - Update source settings

### Agent Operations
- `clarification_reply` - Provide additional context to agents
- `execute_workflow` - Run multi-agent workflows
- `get_workflow_status` - Check workflow execution status

### Analysis & Tools
- `analyze_code` - Code quality and security analysis
- `extract_entities` - Extract structured data
- `generate_summary` - Summarize documents
- `check_policy_compliance` - Verify policy adherence

## Verification

Test your MCP connection:

```bash
# Check ContextIQ health
curl http://localhost:8000/healthz

# Test MCP SSE handshake
curl --max-time 5 \
   -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
   -H "Accept: text/event-stream" \
   http://localhost:8000/mcp/sse/
```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   - Ensure ContextIQ is running: `docker compose ps`
   - Check API logs: `docker compose logs api`

2. **Authentication Failed**
   - Verify token: `echo $CONTEXTIQ_TOKEN`
   - Check token expiry (JWT)
   - Ensure proper permissions

3. **Tools Not Appearing**
   - Restart AI assistant after config changes
   - Verify JSON syntax in config file
   - Check AI assistant logs for errors

### Debug Mode

Enable debug logging in ContextIQ:

```bash
export CONTEXTIQ_LOG_LEVEL=DEBUG
docker compose restart api
docker compose logs -f api
```

## Security Best Practices

1. ✅ **Use Environment Variables** - Never hardcode tokens
2. ✅ **Separate Environments** - Different tokens for dev/prod
3. ✅ **HTTPS in Production** - Always use TLS
4. ✅ **Regular Token Rotation** - Update tokens periodically
5. ✅ **Monitor Access** - Enable audit logging
6. ✅ **Principle of Least Privilege** - Grant minimal permissions

## Architecture

```
┌─────────────────┐
│  AI Assistant   │ (Claude, Cursor, VS Code, etc.)
└────────┬────────┘
         │ MCP over HTTP/WebSocket
         │
┌────────▼────────┐
│ ContextIQ       │
│ API + MCP       │ :8000/mcp/sse/ or /mcp/ws
└────────┬────────┘
         │
    ┌────┴────┬──────────┬──────────┐
    │         │          │          │
┌───▼──┐ ┌───▼──┐  ┌───▼───┐  ┌───▼────┐
│Agent │ │Index │  │Knowl- │  │Govern- │
│Worker│ │ing   │  │edge   │  │ance    │
└──────┘ └──────┘  └───────┘  └────────┘
```

## Production Deployment

For production deployments:

1. **Use HTTPS**
   ```json
   {
     "url": "https://contextiq.example.com/mcp/sse"
   }
   ```

2. **Configure Ingress**
   - See [k8s/ingress-nginx/](../../k8s/ingress-nginx/)
   - Enable TLS termination
   - Set up rate limiting

3. **Load Balancing**
   - Sticky sessions for WebSocket
   - Health checks enabled
   - Proper timeouts configured

4. **Monitoring**
   - Track MCP request metrics
   - Monitor tool invocation rates
   - Set up alerting

## Related Documentation

- [ContextIQ BRD - MCP Gateway Section](../BRD.md#15-enterprise-mcp-gateway)
- [MCP Response Schemas](../api/mcp-response-schemas.md)
- [Connector SDK](../connector-sdk.md)
- [Enterprise Tools Implementation](../enterprise-tools-implementation.md)

## Support

For questions or issues:
- Check [Troubleshooting](#troubleshooting) section above
- Review API logs: `docker compose logs api`
- See [runbooks](../runbooks/) for operational guides
- Contact: support@contextiq.example.com

## Contributing

When adding new AI assistant configurations:
1. Create a new `mcp-{assistant-name}.md` file
2. Follow the existing structure
3. Include setup steps, examples, and troubleshooting
4. Update this README with links
5. Test the configuration before committing

## License

See [LICENSE](../../LICENSE) file in project root.
