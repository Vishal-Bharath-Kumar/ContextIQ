# ContextIQ MCP Configuration for VS Code (GitHub Copilot)

## Location
`.vscode/mcp.json` in your workspace root

## Configuration

Create or update `.vscode/mcp.json`:

```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "Content-Type": "application/json"
      },
      "description": "ContextIQ Enterprise MCP Server"
    }
  }
}
```

## Setup Steps

1. **Create Configuration File**
   ```bash
   # In your project root
   mkdir -p .vscode
   touch .vscode/mcp.json
   ```

2. **Set Environment Variable**
   
   Add to your `.env` file in project root:
   ```bash
   CONTEXTIQ_TOKEN=your-jwt-token-here
   ```
   
   Or add to your shell profile:
   ```bash
   export CONTEXTIQ_TOKEN="your-jwt-token-here"
   ```

3. **Reload VS Code**
   - Press `Cmd+Shift+P` (macOS) or `Ctrl+Shift+P` (Windows/Linux)
   - Type "Developer: Reload Window"
   - Press Enter

4. **Verify Connection**
   - Open GitHub Copilot Chat
   - Type: `@workspace list available MCP servers`

## Workspace-Specific Configuration

For different repositories, create separate `.vscode/mcp.json` files:

### Frontend Repository
```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Repository": "frontend-app",
        "X-Project": "web-platform"
      }
    }
  }
}
```

### Backend Repository
```json
{
  "servers": {
    "contextiq": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Repository": "backend-api",
        "X-Project": "core-services"
      }
    }
  }
}
```

## Using ContextIQ with GitHub Copilot

### In Copilot Chat
```
Search ContextIQ for authentication implementations

Retrieve context from ContextIQ about our API gateway

List knowledge sources in ContextIQ

Sync the GitHub repository in ContextIQ
```

### With @workspace Context
```
@workspace using ContextIQ, find all database migrations

@workspace search ContextIQ for security best practices
```

### Inline Suggestions
GitHub Copilot will automatically use ContextIQ context when:
- Writing code related to enterprise patterns
- Implementing features similar to existing code
- Following organizational standards

## Multi-Workspace Configuration

For VS Code Multi-root Workspaces, create a shared `mcp.json`:

```json
{
  "servers": {
    "contextiq-frontend": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Repository": "frontend"
      }
    },
    "contextiq-backend": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Repository": "backend"
      }
    },
    "contextiq-infra": {
      "type": "http",
      "url": "http://localhost:8080/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${env:CONTEXTIQ_TOKEN}",
        "X-Repository": "infrastructure"
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

## Environment Variables in VS Code

### Option 1: Workspace .env file
Create `.env` in project root:
```bash
CONTEXTIQ_TOKEN=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
CONTEXTIQ_PROD_TOKEN=production-token-here
```

Add `.env` to `.gitignore`:
```bash
echo .env >> .gitignore
```

### Option 2: VS Code Settings
Add to `.vscode/settings.json`:
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

### Option 3: System Environment
Add to shell profile (`~/.zshrc`, `~/.bashrc`):
```bash
export CONTEXTIQ_TOKEN="your-token-here"
```

## Troubleshooting

### MCP Server Not Loading
1. **Check JSON syntax**:
   ```bash
   cat .vscode/mcp.json | jq .
   ```

2. **Verify environment variable**:
   - Open VS Code Integrated Terminal
   - Run: `echo $CONTEXTIQ_TOKEN`

3. **Check Output Panel**:
   - View → Output
   - Select "GitHub Copilot" from dropdown
   - Look for MCP-related messages

### Connection Refused
```bash
# Verify ContextIQ is running
docker compose ps

# Test endpoint
curl -H "Authorization: Bearer $CONTEXTIQ_TOKEN" \
     http://localhost:8080/mcp/sse
```

### Tools Not Available
- Ensure GitHub Copilot extension is up to date
- Reload VS Code window
- Check Copilot status in status bar
- Try disabling/re-enabling Copilot

### Authentication Errors
- Verify token hasn't expired
- Check token permissions
- Regenerate token from ContextIQ auth service

## VS Code Tasks Integration

Create `.vscode/tasks.json` to manage ContextIQ:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Start ContextIQ",
      "type": "shell",
      "command": "docker compose up -d",
      "problemMatcher": [],
      "group": "build"
    },
    {
      "label": "Stop ContextIQ",
      "type": "shell",
      "command": "docker compose down",
      "problemMatcher": []
    },
    {
      "label": "Check ContextIQ MCP",
      "type": "shell",
      "command": "curl -H 'Authorization: Bearer ${CONTEXTIQ_TOKEN}' http://localhost:8080/mcp/sse",
      "problemMatcher": []
    }
  ]
}
```

Run tasks with `Cmd+Shift+P` → "Tasks: Run Task"

## Advanced Features

### Code Actions
ContextIQ can provide code actions through Copilot:
- Right-click in editor
- Select "Copilot" → "Ask ContextIQ"

### Hover Information
Hover over symbols to get ContextIQ-enhanced documentation

### IntelliSense
ContextIQ context automatically enhances autocomplete suggestions

## Best Practices

1. **Workspace-Specific Configs**: Each repo has its own `.vscode/mcp.json`
2. **Environment Separation**: Use different tokens for dev/staging/prod
3. **Secure Tokens**: Never commit tokens to version control
4. **Regular Updates**: Keep GitHub Copilot extension updated
5. **Monitor Usage**: Check VS Code Output panel for MCP activity

## Example Workflows

### Security Review
```
1. Open file in VS Code
2. Select code block
3. Copilot Chat: "Use ContextIQ to analyze this for security issues"
```

### Implementation Pattern
```
1. Start typing a new function
2. Copilot suggests based on ContextIQ enterprise patterns
3. Accept suggestion with Tab
```

### Documentation Search
```
Copilot Chat: "Search ContextIQ for documentation about our auth flow"
```

### Cross-Repository Reference
```
Copilot Chat: "Using ContextIQ, show me how user authentication is 
implemented in both the frontend and backend repos"
```

## Extensions Compatibility

ContextIQ MCP works alongside:
- GitHub Copilot
- GitHub Copilot Chat
- Cline (formerly Claude Dev)
- Continue
- Roo Code
- Cursor (when running in VS Code compatibility mode)

## Logs and Debugging

### Enable Debug Logging
Add to `.vscode/settings.json`:
```json
{
  "github.copilot.advanced": {
    "debug.logLevel": "debug"
  }
}
```

### View Logs
1. View → Output
2. Select "GitHub Copilot" or "GitHub Copilot Chat"
3. Filter for "MCP" or "ContextIQ"

### Network Inspection
```bash
# Monitor MCP requests
docker compose logs -f gateway | grep MCP
```

## Support

For issues:
1. Check VS Code Output panel
2. Review ContextIQ gateway logs: `docker compose logs gateway`
3. Verify configuration: `cat .vscode/mcp.json | jq .`
4. Test connection: Run "Check ContextIQ MCP" task
