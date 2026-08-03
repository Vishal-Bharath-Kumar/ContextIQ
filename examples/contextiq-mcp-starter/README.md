# ContextIQ MCP Starter

Copy these files into the root of any repository where you want GitHub Copilot in VS Code to talk to a local ContextIQ MCP server.

## What This Includes

- `.vscode/mcp.json` for the `contextiq` HTTP MCP server
- `.vscode/tasks.json` for one-time setup and automatic token refresh on folder open
- `.propel/tools/refresh_mcp_token_input.py` for local dev login and token rewrite
- `.env.example` for optional environment variables

## Copy Into Another Repo

From this folder, copy the hidden files and folders into the target repository root so the destination ends up with:

```text
.env.example
.propel/tools/refresh_mcp_token_input.py
.vscode/mcp.json
.vscode/tasks.json
```

The starter now uses the same `.propel/tools` layout as the working ContextIQ workspace, so the copied tasks resolve the refresh helper without further path changes.

If you want a single install command instead of manual copying, run:

```bash
./examples/contextiq-mcp-starter/install.sh /path/to/target-repo
```

That copies the starter files into the target repository with a sanitized `.vscode/mcp.json` that still references `${env:CONTEXTIQ_TOKEN}`.

## First-Time Setup

1. Start the local ContextIQ backend so `http://localhost:8000/mcp/` and `http://localhost:8000/auth/dev-login` are reachable.
2. Open the target repository in VS Code.
3. Run the `setup-contextiq-dev-login` task once.
4. Reload the VS Code window.

On macOS, the setup task stores the local dev credentials in Keychain. After that, the `refresh-contextiq-dev-token` folder-open task refreshes the token automatically on reload.

## Alternatives

- If you already have a bearer token, set `CONTEXTIQ_TOKEN` in your environment and skip the setup task.
- If you do not want credential prompts, set `CONTEXTIQ_DEV_USERNAME` and `CONTEXTIQ_DEV_PASSWORD` in your environment before opening the repo.

## Notes

- The tracked `mcp.json` file stays sanitized with `Bearer ${env:CONTEXTIQ_TOKEN}`.
- Running the setup task rewrites `.vscode/mcp.json` locally with a fresh bearer token for the current repo.
- The folder-open task exits cleanly when cached credentials are unavailable.