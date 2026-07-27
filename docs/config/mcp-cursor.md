# ContextIQ MCP Configuration for Cursor

## Location
- **macOS/Linux**: `~/.cursor/mcp.json`
- **Windows**: `%USERPROFILE%\.cursor\mcp.json`

## Configuration

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

## Setup Steps

1. **Create MCP Config File**
   ```bash
   # macOS/Linux
   mkdir -p ~/.cursor
   touch ~/.cursor/mcp.json
   
   # Windows PowerShell
   New-Item -Path "$env:USERPROFILE\.cursor" -ItemType Directory -Force
   New-Item -Path "$env:USERPROFILE\.cursor\mcp.json" -ItemType File
   ```

2. **Set Environment Variable**
   ```bash
   # macOS/Linux - Add to ~/.zshrc or ~/.bashrc
   export CONTEXTIQ_TOKEN="your-jwt-token-here"
   
   # Windows PowerShell - Add to $PROFILE
   $env:CONTEXTIQ_TOKEN = "your-jwt-token-here"
   ```

3. **Edit Config File**
   Copy the configuration above into `~/.cursor/mcp.json`

4. **Restart Cursor**
   - Quit Cursor completely (Cmd+Q on macOS, Alt+F4 on Windows)
   - Reopen Cursor
   - Open a project

5. **Verify in Cursor**
   - Open Cursor Settings (Cmd+, or Ctrl+,)
   - Navigate to Extensions → MCP
   - ContextIQ should appear in the list of servers

## WebSocket Configuration (Alternative)

For real-time bidirectional communication:

```json
{
  "servers": {
    "contextiq": {
      "type": "websocket",
      "url": "ws://localhost:8080/mcp/ws",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

## Multi-Repository Configuration

Work with multiple repositories simultaneously:

```json
{
  "servers": {
    "contextiq-main": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Repository": "main-app",
        "Content-Type": "application/json"
      }
    },
    "contextiq-microservices": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Repository": "microservices",
        "Content-Type": "application/json"
      }
    }
  }
}
```

## Production Configuration

```json
{
  "servers": {
    "contextiq-prod": {
      "type": "http",
      "url": "https://contextiq.example.com/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_PROD_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

## Using ContextIQ in Cursor

### Via Chat Interface
Press Cmd+L (macOS) or Ctrl+L (Windows) to open Cursor Chat:

```
@contextiq search for authentication implementations
```

### Via Inline Chat
Press Cmd+K (macOS) or Ctrl+K (Windows) in the editor:

```
@contextiq analyze this code for security issues
```

### Available Commands

```
@contextiq semantic_search [query]
@contextiq retrieve_context [document_id]
@contextiq list_sources
@contextiq sync_source [source_id]
@contextiq execute_workflow [workflow_name]
```

## Environment Variables

### macOS/Linux
Add to `~/.zshrc` or `~/.bashrc`:

```bash
# ContextIQ MCP
export CONTEXTIQ_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
export CONTEXTIQ_PROD_TOKEN="production-token"

# Optional: Custom endpoint
export CONTEXTIQ_MCP_URL="http://localhost:8080/mcp/sse"
```

Reload:
```bash
source ~/.zshrc
```

### Windows PowerShell
Add to PowerShell profile (`$PROFILE`):

```powershell
# ContextIQ MCP
$env:CONTEXTIQ_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
$env:CONTEXTIQ_PROD_TOKEN = "production-token"
```

Reload:
```powershell
. $PROFILE
```

## Troubleshooting

### MCP Not Loading
1. Check config file syntax:
   ```bash
   cat ~/.cursor/mcp.json | jq .
   ```
2. Verify environment variable:
   ```bash
   echo $CONTEXTIQ_TOKEN
   ```
3. Check Cursor logs:
   - Open Command Palette (Cmd+Shift+P / Ctrl+Shift+P)
   - Type "Developer: Open Logs Folder"
   - Look for MCP-related errors

### Connection Issues
```bash
# Test endpoint directly
curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
     http://localhost:8080/mcp/sse
```

### Server Not Appearing in List
- Ensure Cursor is completely closed before editing config
- Verify JSON is valid (no trailing commas, proper quotes)
- Check file permissions: `chmod 644 ~/.cursor/mcp.json`

### Authentication Failures
- Verify token is not expired (check JWT expiry)
- Ensure token has correct permissions
- Try regenerating the token

## Advanced Configuration

### Custom Timeouts
```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
      },
      "timeout": 60000,
      "keepAlive": true
    }
  }
}
```

### Proxy Support
```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "proxy": "http://proxy.example.com:8080",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}"
      }
    }
  }
}
```

### Debug Mode
```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Debug": "true"
      },
      "verbose": true
    }
  }
}
```

## Best Practices

1. **Use Environment Variables**: Never hardcode tokens in config files
2. **Separate Environments**: Use different configs for dev/staging/prod
3. **Regular Token Rotation**: Update tokens periodically
4. **Monitor Usage**: Check Cursor MCP logs for errors
5. **Version Control**: Add `mcp.json` to `.gitignore` if committing config

## Examples

### Search Across Repositories
```javascript
// In Cursor Chat
@contextiq semantic_search "payment processing error handling"
```

### Analyze Code Security
```javascript
// Select code in editor, then Cmd+K
@contextiq analyze_code --security-focus
```

### Sync Knowledge Sources
```javascript
@contextiq sync_source github-repo-1
@contextiq sync_source confluence-docs
```

### Execute Multi-Agent Workflow
```javascript
@contextiq execute_workflow "code-review-and-security-scan"
```
