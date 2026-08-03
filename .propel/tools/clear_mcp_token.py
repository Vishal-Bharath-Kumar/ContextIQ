from __future__ import annotations

import json
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[2] / ".vscode" / "mcp.json"
DEFAULT_AUTHORIZATION = "Bearer ${env:CONTEXTIQ_TOKEN}"


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())
    servers = config.get("servers")
    if not isinstance(servers, dict) or "contextiq" not in servers:
        raise SystemExit("Could not find 'contextiq' server in .vscode/mcp.json")

    headers = servers["contextiq"].get("headers")
    if not isinstance(headers, dict):
        raise SystemExit("Could not find 'headers' for ContextIQ server in .vscode/mcp.json")

    headers["Authorization"] = DEFAULT_AUTHORIZATION
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print("Cleared ContextIQ MCP bearer token from mcp.json")


if __name__ == "__main__":
    main()