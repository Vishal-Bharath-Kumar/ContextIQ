from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONFIG_PATH = Path(__file__).resolve().parent.parent / ".vscode" / "mcp.json"
DEV_LOGIN_URL = "http://localhost:8000/auth/dev-login"
KEYCHAIN_SERVICE = "ContextIQ VS Code Dev Login"
KEYCHAIN_ACCOUNT = "credentials"
USERNAME_ENV_VAR = "CONTEXTIQ_DEV_USERNAME"
PASSWORD_ENV_VAR = "CONTEXTIQ_DEV_PASSWORD"


@dataclass(frozen=True)
class DevCredentials:
    username: str
    password: str
    source: str
    persist_after_success: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("username", nargs="?")
    parser.add_argument("password", nargs="?")
    parser.add_argument("--url", default=DEV_LOGIN_URL)
    parser.add_argument(
        "--skip-if-missing",
        action="store_true",
        help="Exit successfully when no cached credentials are available.",
    )
    return parser.parse_args()


def _supports_macos_keychain() -> bool:
    return sys.platform == "darwin"


def _missing_credentials_message() -> str:
    return (
        "No cached ContextIQ dev credentials were found. "
        "Run the 'setup-contextiq-dev-login' VS Code task once or export "
        f"{USERNAME_ENV_VAR}/{PASSWORD_ENV_VAR}."
    )


def _load_credentials_from_env() -> DevCredentials | None:
    username = os.environ.get(USERNAME_ENV_VAR)
    password = os.environ.get(PASSWORD_ENV_VAR)
    if not username or not password:
        return None
    return DevCredentials(username=username, password=password, source="environment")


def _load_credentials_from_keychain() -> DevCredentials | None:
    if not _supports_macos_keychain():
        return None

    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as error:
        raise SystemExit(
            "Stored ContextIQ dev credentials are invalid. "
            "Run the 'setup-contextiq-dev-login' task again."
        ) from error

    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not username:
        raise SystemExit(
            "Stored ContextIQ dev credentials are missing a username. "
            "Run the 'setup-contextiq-dev-login' task again."
        )
    if not isinstance(password, str) or not password:
        raise SystemExit(
            "Stored ContextIQ dev credentials are missing a password. "
            "Run the 'setup-contextiq-dev-login' task again."
        )

    return DevCredentials(username=username, password=password, source="macOS Keychain")


def _store_credentials_in_keychain(username: str, password: str) -> None:
    if not _supports_macos_keychain():
        return

    payload = json.dumps({"username": username, "password": password})
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
            payload,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error_output = (result.stderr or result.stdout).strip()
        raise SystemExit(
            "Could not store ContextIQ dev credentials in macOS Keychain"
            + (f": {error_output}" if error_output else "")
        )


def resolve_credentials(args: argparse.Namespace) -> DevCredentials:
    if bool(args.username) != bool(args.password):
        raise SystemExit("Pass both username and password, or neither.")

    if args.username and args.password:
        return DevCredentials(
            username=args.username,
            password=args.password,
            source="task input",
            persist_after_success=_supports_macos_keychain(),
        )

    env_credentials = _load_credentials_from_env()
    if env_credentials is not None:
        return env_credentials

    keychain_credentials = _load_credentials_from_keychain()
    if keychain_credentials is not None:
        return keychain_credentials

    message = _missing_credentials_message()
    if args.skip_if_missing:
        print(f"Skipping ContextIQ token refresh: {message}")
        raise SystemExit(0)
    raise SystemExit(message)


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
    credentials = resolve_credentials(args)
    token = fetch_token(credentials.username, credentials.password, args.url)
    if credentials.persist_after_success:
        _store_credentials_in_keychain(credentials.username, credentials.password)
    update_mcp_config(token)
    print(
        "Updated ContextIQ MCP header with a fresh dev token "
        f"using {credentials.source} credentials"
    )


if __name__ == "__main__":
    main()