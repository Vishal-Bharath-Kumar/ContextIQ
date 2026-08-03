# ContextIQ MCP Configuration for Continue

## Location
- **macOS/Linux**: `~/.continue/config.json`
- **Windows**: `%USERPROFILE%\.continue\config.json`

## Configuration

```json
{
  "mcpServers": [
    {
      "name": "contextiq",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  ]
}
```

## Complete Configuration Example

```json
{
  "models": [
    {
      "title": "Claude 3.5 Sonnet",
      "provider": "anthropic",
      "model": "claude-3-5-sonnet-20241022",
      "apiKey": "${ANTHROPIC_API_KEY}"
    }
  ],
  "mcpServers": [
    {
      "name": "contextiq",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      },
      "description": "ContextIQ Enterprise Knowledge & Tools",
      "enabled": true
    }
  ],
  "tabAutocompleteModel": {
    "title": "Starcoder",
    "provider": "together",
    "model": "starcoder-16b"
  }
}
```

## Setup Steps

1. **Install Continue Extension**
   - Open VS Code
   - Go to Extensions (Cmd+Shift+X / Ctrl+Shift+X)
   - Search for "Continue"
   - Install the extension

2. **Create Configuration File**
   ```bash
   # macOS/Linux
   mkdir -p ~/.continue
   touch ~/.continue/config.json
   
   # Windows PowerShell
   New-Item -Path "$env:USERPROFILE\.continue" -ItemType Directory -Force
   New-Item -Path "$env:USERPROFILE\.continue\config.json" -ItemType File
   ```

3. **Set Environment Variables**
   ```bash
   # macOS/Linux - Add to ~/.zshrc or ~/.bashrc
   export CONTEXTIQ_TOKEN="your-jwt-token-here"
   
   # Windows PowerShell - Add to $PROFILE
   $env:CONTEXTIQ_TOKEN = "your-jwt-token-here"
   ```

4. **Edit Configuration**
   - Open VS Code
   - Press Cmd+Shift+P / Ctrl+Shift+P
   - Type "Continue: Open Config"
   - Paste the configuration above

5. **Reload VS Code**
   - Press Cmd+Shift+P / Ctrl+Shift+P
   - Type "Developer: Reload Window"
   - Press Enter

## WebSocket Configuration

For real-time bidirectional communication:

Note: the default local Docker Compose stack publishes the SSE endpoint on the `api` service. Use this WebSocket option only if you separately expose the WebSocket route.

```json
{
  "mcpServers": [
    {
      "name": "contextiq-ws",
      "type": "websocket",
      "url": "ws://localhost:8000/mcp/ws",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}"
      },
      "reconnect": true
    }
  ]
}
```

## Multi-Repository Configuration

Work with multiple repositories:

```json
{
  "mcpServers": [
    {
      "name": "contextiq-frontend",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "X-Repository": "frontend-app",
        "Content-Type": "application/json"
      }
    },
    {
      "name": "contextiq-backend",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "X-Repository": "backend-api",
        "Content-Type": "application/json"
      }
    },
    {
      "name": "contextiq-docs",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "X-Repository": "documentation",
        "Content-Type": "application/json"
      }
    }
  ]
}
```

## Production Configuration

```json
{
  "mcpServers": [
    {
      "name": "contextiq-production",
      "type": "http",
      "url": "https://contextiq.example.com/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_PROD_TOKEN}",
        "Content-Type": "application/json"
      },
      "timeout": 60000
    }
  ]
}
```

## Using ContextIQ in Continue

### Chat Interface
Press `Cmd+L` (macOS) or `Ctrl+L` (Windows/Linux) to open Continue Chat:

```
@contextiq search for authentication implementations

/contextiq semantic_search database migration patterns

Ask ContextIQ about our API documentation
```

### Inline Edit
Select code and press `Cmd+I` (macOS) or `Ctrl+I` (Windows/Linux):

```
@contextiq analyze this for security issues

@contextiq suggest improvements based on our patterns
```

### Available Commands

#### Search & Retrieval
```
@contextiq semantic_search [query]
@contextiq retrieve_context [document_id]
@contextiq hybrid_search [query]
```

#### Knowledge Sources
```
@contextiq list_sources
@contextiq sync_source [source_id]
@contextiq get_source_status [source_id]
```

#### Analysis
```
@contextiq analyze_code [focus_area]
@contextiq extract_entities
@contextiq check_policy_compliance
```

## Environment Variables

### macOS/Linux
Add to `~/.zshrc` or `~/.bashrc`:

```bash
# ContextIQ MCP Configuration
export CONTEXTIQ_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
export CONTEXTIQ_PROD_TOKEN="production-token"

# Optional
export CONTEXTIQ_MCP_URL="http://localhost:8000/mcp/sse/"
export CONTEXTIQ_LOG_LEVEL="DEBUG"

# Reload
source ~/.zshrc
```

### Windows PowerShell
Add to `$PROFILE`:

```powershell
# ContextIQ MCP Configuration
$env:CONTEXTIQ_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
$env:CONTEXTIQ_PROD_TOKEN = "production-token"

# Reload
. $PROFILE
```

### VS Code Settings.json
Alternatively, add to `.vscode/settings.json`:

```json
{
  "terminal.integrated.env.osx": {
    "CONTEXTIQ_TOKEN": "your-token-here"
  },
  "terminal.integrated.env.linux": {
    "CONTEXTIQ_TOKEN": "your-token-here"
  },
  "terminal.integrated.env.windows": {
    "CONTEXTIQ_TOKEN": "your-token-here"
  }
}
```

## Troubleshooting

### Continue Not Loading MCP Server

1. **Verify Configuration**
   ```bash
   cat ~/.continue/config.json | jq .
   ```

2. **Check Environment Variable**
   ```bash
   echo $CONTEXTIQ_TOKEN
   ```

3. **View Continue Logs**
   - Press `Cmd+Shift+P` / `Ctrl+Shift+P`
   - Type "Developer: Open Extension Logs Folder"
   - Look for "continue" folder
   - Check logs for errors

### Connection Issues

```bash
# Test ContextIQ endpoint
curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
  -H "Accept: text/event-stream" \
  http://localhost:8000/mcp/sse/

# Verify ContextIQ is running
docker compose ps

# Check API logs
docker compose logs -f api
```

### Authentication Errors

- Verify token is set: `echo $CONTEXTIQ_TOKEN`
- Check token hasn't expired (JWT expiry)
- Ensure token has correct permissions
- Try regenerating token

### Tools Not Appearing

1. Reload VS Code window
2. Restart Continue extension
3. Check Continue extension version (update if needed)
4. Verify ContextIQ API is healthy: `curl http://localhost:8000/healthz`

## Advanced Configuration

### Custom Timeouts

```json
{
  "mcpServers": [
    {
      "name": "contextiq",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}"
      },
      "timeout": 60000,
      "retryAttempts": 3,
      "retryDelay": 1000
    }
  ]
}
```

### Proxy Support

```json
{
  "mcpServers": [
    {
      "name": "contextiq",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}"
      },
      "proxy": "http://proxy.example.com:8080"
    }
  ]
}
```

### Custom Headers

```json
{
  "mcpServers": [
    {
      "name": "contextiq",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "X-Repository": "my-repo",
        "X-Project": "my-project",
        "X-Team": "platform",
        "X-Environment": "dev",
        "X-User-Agent": "Continue-VSCode"
      }
    }
  ]
}
```

## Integration with Continue Features

### Context Providers
Continue can combine ContextIQ with other context providers:

```json
{
  "contextProviders": [
    {
      "name": "code",
      "params": {}
    },
    {
      "name": "diff",
      "params": {}
    },
    {
      "name": "terminal",
      "params": {}
    },
    {
      "name": "problems",
      "params": {}
    }
  ],
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

### Slash Commands
Create custom slash commands that use ContextIQ:

```json
{
  "slashCommands": [
    {
      "name": "search-enterprise",
      "description": "Search enterprise knowledge with ContextIQ",
      "run": "@contextiq semantic_search $input"
    },
    {
      "name": "analyze-security",
      "description": "Analyze selected code for security issues",
      "run": "@contextiq analyze_code --security-focus $selectedCode"
    }
  ]
}
```

## Examples

### Code Review Workflow
1. Select code in editor
2. Press `Cmd+I` / `Ctrl+I`
3. Type: `@contextiq analyze this code against our enterprise patterns`
4. Review suggestions and apply changes

### Documentation Search
1. Press `Cmd+L` / `Ctrl+L` to open Continue Chat
2. Type: `@contextiq search for API documentation about authentication`
3. Review results
4. Ask follow-up questions

### Implementation Pattern
1. Start typing a new function
2. Press `Cmd+Shift+Space` for autocomplete
3. Continue suggests code based on ContextIQ patterns
4. Accept with Tab

### Cross-Repository Analysis
```
@contextiq-frontend search for login component
@contextiq-backend search for auth API
Compare the frontend and backend authentication approaches
```

## Best Practices

1. **Use Specific Queries**: Be explicit in your ContextIQ queries
2. **Leverage Context**: Combine ContextIQ with Continue's other context providers
3. **Custom Commands**: Create slash commands for frequent operations
4. **Monitor Performance**: Check logs for slow queries
5. **Update Regularly**: Keep Continue extension and ContextIQ updated

## Performance Tips

```json
{
  "mcpServers": [
    {
      "name": "contextiq",
      "type": "http",
      "url": "http://localhost:8000/mcp/sse/",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}"
      },
      "timeout": 30000,
      "cache": true,
      "cacheTTL": 300000,
      "maxConcurrentRequests": 3
    }
  ]
}
```

## Keyboard Shortcuts

Default Continue shortcuts that work with ContextIQ:

- `Cmd+L` / `Ctrl+L` - Open Chat
- `Cmd+I` / `Ctrl+I` - Inline Edit
- `Cmd+Shift+R` / `Ctrl+Shift+R` - Regenerate
- `Cmd+Backspace` / `Ctrl+Backspace` - Cancel

## Support

- **Continue Logs**: Extensions → Continue → Right-click → Show Logs
- **ContextIQ Logs**: `docker compose logs -f api`
- **Test Connection**: `curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" -H "Accept: text/event-stream" http://localhost:8000/mcp/sse/`
- **Documentation**: 
  - [Continue Docs](https://continue.dev/docs)
  - [ContextIQ MCP Setup](./mcp-client-setup.md)

## Related Extensions

Continue works well with:
- GitHub Copilot (complementary)
- GitLens
- Error Lens
- Code Spell Checker

## Migration from Other Tools

### From GitHub Copilot
Continue + ContextIQ provides:
- Enterprise knowledge access
- Custom context providers
- Configurable models
- Privacy control

### From Cursor
Continue offers:
- Open source
- More customization
- Multiple model support
- MCP integration

## Contributing

To improve Continue + ContextIQ integration:
1. Report issues on Continue GitHub
2. Share configuration examples
3. Document workflows
4. Provide feedback to ContextIQ team
