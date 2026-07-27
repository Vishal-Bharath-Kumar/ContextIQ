# ContextIQ MCP Configuration for Windsurf

## Location
- **macOS**: `~/.windsurf/mcp.json`
- **Windows**: `%USERPROFILE%\.windsurf\mcp.json`
- **Linux**: `~/.config/windsurf/mcp.json`

## Configuration

```json
{
  "mcpServers": {
    "contextiq": {
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

## Alternative Configuration (Detailed)

```json
{
  "mcpServers": {
    "contextiq": {
      "name": "ContextIQ Enterprise",
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "headers": {
        "Content-Type": "application/json"
      },
      "timeout": 30000,
      "enabled": true
    }
  }
}
```

## Setup Steps

1. **Create Configuration Directory**
   ```bash
   # macOS/Linux
   mkdir -p ~/.windsurf
   touch ~/.windsurf/mcp.json
   
   # Windows PowerShell
   New-Item -Path "$env:USERPROFILE\.windsurf" -ItemType Directory -Force
   New-Item -Path "$env:USERPROFILE\.windsurf\mcp.json" -ItemType File
   ```

2. **Set Environment Variable**
   ```bash
   # macOS/Linux - Add to ~/.zshrc or ~/.bashrc
   export CONTEXTIQ_TOKEN="your-jwt-token-here"
   source ~/.zshrc
   
   # Windows PowerShell - Add to $PROFILE
   $env:CONTEXTIQ_TOKEN = "your-jwt-token-here"
   ```

3. **Edit Configuration**
   Copy the configuration above into `~/.windsurf/mcp.json`

4. **Restart Windsurf**
   - Quit Windsurf completely
   - Reopen Windsurf
   - Open a project

5. **Verify Connection**
   - Open Windsurf AI Chat
   - Type: `list available MCP servers`

## WebSocket Configuration (Alternative)

For real-time updates:

```json
{
  "mcpServers": {
    "contextiq": {
      "url": "ws://localhost:8080/mcp/ws",
      "transport": "websocket",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "reconnect": true,
      "reconnectInterval": 5000
    }
  }
}
```

## Multi-Repository Setup

Configure multiple ContextIQ connections:

```json
{
  "mcpServers": {
    "contextiq-frontend": {
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "headers": {
        "X-Repository": "frontend-app"
      }
    },
    "contextiq-backend": {
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "headers": {
        "X-Repository": "backend-api"
      }
    }
  }
}
```

## Production Configuration

```json
{
  "mcpServers": {
    "contextiq-prod": {
      "url": "https://contextiq.example.com/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_PROD_TOKEN}"
      },
      "headers": {
        "Content-Type": "application/json"
      },
      "timeout": 60000,
      "retry": {
        "enabled": true,
        "maxAttempts": 3,
        "backoff": "exponential"
      }
    }
  }
}
```

## Using ContextIQ in Windsurf

### AI Chat Commands
```
@contextiq search for authentication implementations

@contextiq retrieve documentation about API gateway

@contextiq list all knowledge sources

@contextiq analyze this code for security issues
```

### Inline Assistance
- Select code in editor
- Press `Cmd+Shift+K` (macOS) or `Ctrl+Shift+K` (Windows/Linux)
- Type: `@contextiq analyze this`

### Available Tools

#### Search & Retrieval
```
@contextiq semantic_search [query]
@contextiq hybrid_search [query]
@contextiq retrieve_context [doc_id]
```

#### Knowledge Sources
```
@contextiq list_sources
@contextiq sync_source [source_id]
@contextiq get_source_status [source_id]
```

#### Agent Operations
```
@contextiq execute_workflow [workflow_name]
@contextiq clarification_reply [message]
```

## Environment Variables

### macOS/Linux
```bash
# Add to ~/.zshrc or ~/.bashrc
export CONTEXTIQ_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
export CONTEXTIQ_PROD_TOKEN="production-token"
export CONTEXTIQ_MCP_TIMEOUT="30000"

# Reload
source ~/.zshrc
```

### Windows PowerShell
```powershell
# Add to $PROFILE
$env:CONTEXTIQ_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
$env:CONTEXTIQ_PROD_TOKEN = "production-token"

# Reload
. $PROFILE
```

## Troubleshooting

### Server Not Appearing
1. Verify config file exists and is valid JSON:
   ```bash
   cat ~/.windsurf/mcp.json | jq .
   ```
2. Check environment variable:
   ```bash
   echo $CONTEXTIQ_TOKEN
   ```
3. Restart Windsurf completely

### Connection Errors
```bash
# Test ContextIQ endpoint
curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
     http://localhost:8080/mcp/sse

# Check ContextIQ logs
docker compose logs -f gateway
```

### Authentication Failed
- Verify token is valid and not expired
- Check token has proper permissions
- Try regenerating token

### Tools Not Working
- Check Windsurf console logs (Help → Toggle Developer Tools)
- Verify ContextIQ gateway is running: `docker compose ps`
- Test connection with curl

## Advanced Features

### Custom Headers
```json
{
  "mcpServers": {
    "contextiq": {
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "headers": {
        "X-Repository": "my-repo",
        "X-Project": "my-project",
        "X-Team": "platform",
        "X-Environment": "dev",
        "X-Debug": "true"
      }
    }
  }
}
```

### Proxy Support
```json
{
  "mcpServers": {
    "contextiq": {
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "proxy": {
        "host": "proxy.example.com",
        "port": 8080,
        "auth": {
          "username": "user",
          "password": "${PROXY_PASSWORD}"
        }
      }
    }
  }
}
```

### Retry Configuration
```json
{
  "mcpServers": {
    "contextiq": {
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "retry": {
        "enabled": true,
        "maxAttempts": 5,
        "initialDelay": 1000,
        "maxDelay": 30000,
        "backoff": "exponential",
        "retryOn": [500, 502, 503, 504]
      }
    }
  }
}
```

## Examples

### Code Analysis Workflow
1. Open a file in Windsurf
2. Select code block
3. AI Chat: `@contextiq analyze this for security vulnerabilities`
4. Review results and apply suggestions

### Documentation Search
1. Open AI Chat
2. Type: `@contextiq search for documentation about authentication`
3. Review results
4. Ask follow-up questions

### Cross-Repository Search
1. Configure multiple MCP servers (frontend, backend)
2. AI Chat: `@contextiq-frontend search for login component`
3. AI Chat: `@contextiq-backend search for authentication API`
4. Compare implementations

## Best Practices

1. **Environment Separation**: Use different configs for dev/staging/prod
2. **Token Security**: Never commit tokens, use environment variables
3. **Regular Updates**: Keep Windsurf updated for latest MCP features
4. **Monitor Usage**: Check Windsurf logs for MCP activity
5. **Test Connections**: Verify connectivity before heavy usage

## Performance Tuning

```json
{
  "mcpServers": {
    "contextiq": {
      "url": "http://localhost:8080/mcp/sse",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${CONTEXTIQ_TOKEN}"
      },
      "timeout": 30000,
      "keepAlive": true,
      "maxConcurrentRequests": 5,
      "requestQueueSize": 100,
      "cache": {
        "enabled": true,
        "ttl": 300000
      }
    }
  }
}
```

## Support

- **Windsurf Logs**: Help → Toggle Developer Tools → Console
- **ContextIQ Logs**: `docker compose logs -f gateway`
- **Test Connection**: `curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" http://localhost:8080/mcp/sse`
- **Documentation**: See [MCP Client Setup Guide](./mcp-client-setup.md)
