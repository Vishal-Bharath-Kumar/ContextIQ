# ContextIQ MCP Configuration for Claude Desktop

## Location
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/claude/claude_desktop_config.json`

## Configuration

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

## Setup Steps

1. **Obtain JWT Token**
   ```bash
   # Login to ContextIQ and obtain your token
   export CONTEXTIQ_TOKEN="your-jwt-token-here"
   ```

2. **Edit Claude Desktop Config**
   - Open Claude Desktop
   - Go to Settings (⚙️) → Developer → Edit Config
   - Add the ContextIQ server configuration
   - Save the file

3. **Restart Claude Desktop**
   - Quit Claude Desktop completely
   - Reopen Claude Desktop
   - The ContextIQ tools should now be available

4. **Verify Connection**
   In Claude Desktop, type:
   ```
   Can you list the available tools from ContextIQ?
   ```

## Production Configuration

For production environments:

```json
{
  "mcpServers": {
    "contextiq-production": {
      "type": "http",
      "url": "https://contextiq.example.com/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_PROD_TOKEN}",
        "Content-Type": "application/json"
      }
    }
  }
}
```

## Multi-Repository Setup

Configure multiple ContextIQ connections for different repositories:

```json
{
  "mcpServers": {
    "contextiq-repo-frontend": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "X-Repository": "frontend-app",
        "Content-Type": "application/json"
      }
    },
    "contextiq-repo-backend": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${CONTEXTIQ_TOKEN}",
        "X-Repository": "backend-api",
        "Content-Type": "application/json"
      }
    }
  }
}
```

## Environment Variables

Add to your shell profile (`~/.zshrc`, `~/.bashrc`):

```bash
# ContextIQ MCP Configuration
export CONTEXTIQ_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
export CONTEXTIQ_PROD_TOKEN="production-token-here"
```

Reload your shell:
```bash
source ~/.zshrc  # or ~/.bashrc
```

## Troubleshooting

### Token Not Found
If Claude can't read the environment variable:
1. Set it globally in your shell profile
2. Restart your terminal completely
3. Restart Claude Desktop
4. Verify: `echo $CONTEXTIQ_TOKEN`

### Connection Refused
- Ensure ContextIQ is running: `docker compose ps`
- Check gateway is accessible: `curl http://localhost:8080/health`
- Verify no firewall blocking port 8080

### Tools Not Appearing
- Check Claude Developer Console for errors
- View logs: Settings → Developer → Logs
- Verify JSON syntax in config file
- Try using WebSocket transport instead:
  ```json
  {
    "type": "websocket",
    "url": "ws://localhost:8080/mcp/ws"
  }
  ```

## Using ContextIQ in Claude

Once configured, you can:

### Search Enterprise Knowledge
```
Search our codebase for authentication implementations
```

### Retrieve Context
```
Show me the latest documentation for our API gateway
```

### Execute Workflows
```
Analyze the security posture of our payment processing code
```

### Multi-Repository Queries
```
Compare the authentication approach in frontend-app vs backend-api
```
