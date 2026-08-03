#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
target_dir="${1:-}"

if [[ -z "$target_dir" ]]; then
  echo "Usage: $0 /path/to/target-repo" >&2
  exit 1
fi

if [[ ! -d "$target_dir" ]]; then
  echo "Target directory does not exist: $target_dir" >&2
  exit 1
fi

mkdir -p "$target_dir/.vscode" "$target_dir/.propel/tools"

cp "$script_dir/.env.example" "$target_dir/.env.example"
cp "$script_dir/.vscode/mcp.json" "$target_dir/.vscode/mcp.json"
cp "$script_dir/.vscode/tasks.json" "$target_dir/.vscode/tasks.json"
cp "$script_dir/.propel/tools/refresh_mcp_token_input.py" "$target_dir/.propel/tools/refresh_mcp_token_input.py"

echo "Installed ContextIQ MCP starter into $target_dir"
echo "Next: open the target repo in VS Code and run the 'setup-contextiq-dev-login' task once."