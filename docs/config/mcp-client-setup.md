# ContextIQ MCP Client Configuration Guide

This guide explains how to configure various AI assistants to connect to ContextIQ's Model Context Protocol (MCP) server.

## Overview

ContextIQ exposes its enterprise capabilities through MCP, enabling AI assistants to:

- **Search & Retrieve**: Access enterprise knowledge sources across multiple repositories
- **Execute Tools**: Invoke enterprise tools for analysis, retrieval, and operations
- **Access Resources**: Query indexed documents, code, and structured data
- **Agent Orchestration**: Leverage multi-agent workflows for complex tasks

## Supported AI Assistants

- Claude Desktop
- Cursor
- GitHub Copilot (VS Code)
- Windsurf
- Continue
- Cline
- Roo Code
- Custom MCP clients

---

## Prerequisites

### 1. ContextIQ Server Running

Ensure ContextIQ is running and accessible:

```bash
# Local development
docker compose up -d

# Verify the API service is running
curl http://localhost:8000/healthz
```

### 2. Authentication Token

Obtain a JWT token from your ContextIQ authentication service:

```bash
# Set your token as an environment variable
export CONTEXTIQ_TOKEN="your-jwt-token-here"
```

For production environments:
```bash
export CONTEXTIQ_PROD_TOKEN="your-production-jwt-token"
```

### 3. Network Access

- **Local**: ContextIQ should be accessible at `http://localhost:8000`
- **Production**: Configure your production URL (e.g., `https://contextiq.example.com`)
- Ensure firewall rules allow access to the MCP endpoints

---

## Configuration by AI Assistant

### Claude Desktop

**Location**: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)  
**Location**: `%APPDATA%/Claude/claude_desktop_config.json` (Windows)

```json
{
  "mcpServers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

**Steps**:
1. Open Claude Desktop
2. Go to Settings → Developer → MCP Servers
3. Click "Edit Config"
4. Add the ContextIQ server configuration
5. Save and restart Claude Desktop

---

### Cursor

**Location**: `~/.cursor/mcp.json` (macOS/Linux)  
**Location**: `%USERPROFILE%/.cursor/mcp.json` (Windows)

```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8000/mcp/",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

**Steps**:
1. Create or edit `~/.cursor/mcp.json`
2. Add the ContextIQ configuration
3. Restart Cursor
4. Verify connection in Cursor Settings → MCP

---

### GitHub Copilot (VS Code)

**Location**: `.vscode/mcp.json` in your workspace

```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

**Steps**:
1. Open VS Code in your project
2. Create `.vscode/mcp.json` if it doesn't exist
3. Add the ContextIQ server or copy the starter from `examples/contextiq-mcp-starter`
4. Run `setup-contextiq-dev-login` once if you installed the starter tasks
5. Reload VS Code window
6. Use Copilot Chat to access ContextIQ tools

---

### Windsurf

**Location**: `~/.windsurf/mcp.json`

```json
{
  "mcpServers": {
    "contextiq": {
      "url": "http://localhost:8000/mcp/sse/",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

---

### Continue

**Location**: `~/.continue/config.json`

```json
{
  "mcpServers": [
    {
      "name": "contextiq",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}"
      }
    }
  ]
}
```

---

### Cline / Roo Code

These extensions typically read from `.vscode/mcp.json` in your workspace.

```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

---

## Transport Options

ContextIQ supports two MCP transports:

### VS Code Workspace MCP
- **Endpoint**: `http://localhost:8000/mcp/`
- **Best for**: GitHub Copilot in VS Code, workspace-local `.vscode/mcp.json`
- **Protocol**: MCP over HTTP POST

### Server-Sent Events (SSE) - Recommended
- **Endpoint**: `http://localhost:8000/mcp/sse/`
- **Best for**: Claude Desktop, Cursor, Continue, and other clients that explicitly expect SSE
- **Protocol**: HTTP with streaming responses

### WebSocket (WS)
- **Endpoint**: `ws://localhost:8000/mcp/ws`
- **Note**: the default local Docker Compose stack publishes the SSE endpoint on the `api` service. Use WebSocket only if you separately expose that route.
- **Best for**: Real-time bidirectional communication
- **Protocol**: WebSocket with persistent connection

Example WebSocket configuration:
```json
{
  "contextiq-ws": {
    "type": "websocket",
    "url": "ws://localhost:8000/mcp/ws",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
    }
  }
}
```

---

## Environment Variables

Set these in your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):

```bash
# Local development
export CONTEXTIQ_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

# Production
export CONTEXTIQ_PROD_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

# Custom endpoint
export CONTEXTIQ_MCP_URL="https://contextiq.example.com/mcp/"
```

For Windows PowerShell:
```powershell
$env:CONTEXTIQ_TOKEN = "your-token-here"
```

---

## Available Tools

Once connected, AI assistants can access these ContextIQ tools:

### Retrieval Tools
- `semantic_search`: Search across enterprise knowledge sources
- `hybrid_search`: Combined semantic + keyword search
- `retrieve_context`: Fetch specific documents or code

### Knowledge Source Tools
- `list_sources`: List available knowledge sources
- `sync_source`: Trigger sync for a knowledge source
- `source_status`: Check sync status

### Agent Tools
- `clarification_reply`: Provide additional context to agents
- `execute_workflow`: Run multi-agent workflows

### Analysis Tools
- `analyze_code`: Code quality and security analysis
- `extract_entities`: Extract structured data from documents

---

## Verification

Verify by client type:

```bash
# Health check for all clients
curl http://localhost:8000/healthz

# Test SSE endpoint for SSE-based clients
curl --max-time 5 \
  -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
  -H "Accept: text/event-stream" \
  http://localhost:8000/mcp/sse/
```

For VS Code, reload the window after configuring `.vscode/mcp.json` and confirm the server appears in Copilot Chat. If VS Code asks for a client ID, it did not receive a valid bearer token header.

---

## Troubleshooting

### Connection Refused
- Verify ContextIQ is running: `docker compose ps`
- Check API logs: `docker compose logs api`
- Ensure port 8000 is not blocked

### Authentication Failed
- Verify token is set: `echo $CONTEXTIQ_TOKEN`
- Check token hasn't expired (JWT expiry)
- Ensure token has proper permissions

### Tools Not Appearing
- Restart AI assistant after configuration changes
- Check MCP config file syntax (valid JSON)
- Verify `capabilities.tools` is set to `true`

### Logs
View ContextIQ API logs:
```bash
docker compose logs -f api
```

Enable debug logging:
```bash
export CONTEXTIQ_LOG_LEVEL=DEBUG
docker compose restart api
```

---

## Production Deployment

### Kubernetes

For Kubernetes deployments, configure Ingress for the MCP endpoints:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: contextiq-mcp
  namespace: contextiq
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
  - host: contextiq.example.com
    http:
      paths:
      - path: /mcp
        pathType: Prefix
        backend:
          service:
            name: contextiq-gateway
            port:
              number: 8080
```

### HTTPS/TLS

For production, always use HTTPS:

```json
{
  "contextiq-production": {
    "type": "http",
    "url": "https://contextiq.example.com/mcp/sse",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_PROD_TOKEN}"
    }
  }
}
```

### Load Balancing

When using multiple gateway instances, ensure:
- Sticky sessions for WebSocket connections
- Proper health check endpoints configured
- JWT validation across all instances

---

## Security Best Practices

1. **Never commit tokens** - Use environment variables
2. **Rotate tokens regularly** - Implement token refresh logic
3. **Use HTTPS in production** - Encrypt all traffic
4. **Implement rate limiting** - Protect against abuse
5. **Monitor usage** - Track MCP tool invocations
6. **Audit logs** - Enable gateway audit logging

---

## Multi-Repository Support

ContextIQ supports working across multiple repositories:

### Configuration Example

```json
{
  "contextiq-repo-a": {
    "type": "http",
    "url": "http://localhost:8000/mcp/sse/",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
      "X-Repository": "repo-a",
      "X-Project": "project-alpha"
    }
  },
  "contextiq-repo-b": {
    "type": "http",
    "url": "http://localhost:8000/mcp/sse/",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
      "X-Repository": "repo-b",
      "X-Project": "project-beta"
    }
  }
}
```

### Custom Headers

Use custom headers to scope requests:
- `X-Repository`: Target specific repository
- `X-Project`: Filter by project
- `X-Team`: Scope to team resources
- `X-Environment`: Target dev/staging/prod

---

## Advanced Configuration

### Retry & Timeout

```json
{
  "contextiq": {
    "type": "http",
    "url": "http://localhost:8000/mcp/sse/",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
    },
    "timeout": 30000,
    "retries": 3,
    "retryDelay": 1000
  }
}
```

### Proxy Support

```json
{
  "contextiq": {
    "type": "http",
    "url": "http://localhost:8000/mcp/sse/",
    "proxy": "http://proxy.example.com:8080",
    "headers": {
      "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
    }
  }
}
```

---

## Support

For issues or questions:
- Check logs: `docker compose logs api`
- Review documentation: `docs/api/mcp-response-schemas.md`
- Contact: support@contextiq.example.com

---

## References

- [Model Context Protocol Specification](https://spec.modelcontextprotocol.io/)
- [ContextIQ BRD](../BRD.md#15-enterprise-mcp-gateway)
- [ContextIQ API Documentation](../api/README.md)
