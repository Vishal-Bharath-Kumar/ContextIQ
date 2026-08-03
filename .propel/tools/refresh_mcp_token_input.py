from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONFIG_PATH = Path(__file__).resolve().parents[2] / ".vscode" / "mcp.json"
DEV_LOGIN_URL = "http://localhost:8000/auth/dev-login"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("--url", default=DEV_LOGIN_URL)
    return parser.parse_args()


def fetch_token(username: str, password: str, url: str) -> str:
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Dev login failed with HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise SystemExit(f"Could not reach dev login endpoint: {error.reason}") from error

    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        raise SystemExit("Dev login response did not contain an access_token")
    return token


def update_mcp_config(token: str) -> None:
    config = json.loads(CONFIG_PATH.read_text())
    servers = config.get("servers")
    if not isinstance(servers, dict) or "contextiq" not in servers:
        raise SystemExit("Could not find 'contextiq' server in .vscode/mcp.json")

    headers = servers["contextiq"].get("headers")
    if not isinstance(headers, dict):
        raise SystemExit("Could not find 'headers' for ContextIQ server in .vscode/mcp.json")

    headers["Authorization"] = f"Bearer {token}"
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def main() -> None:
    args = parse_args()
    token = fetch_token(args.username, args.password, args.url)
    update_mcp_config(token)
    print("Updated ContextIQ MCP header with a fresh dev token")


if __name__ == "__main__":
    main()