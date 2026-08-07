"""Helpers for exposing MCP OAuth protected-resource metadata."""
from __future__ import annotations

from typing import Any

from src.auth.keycloak_settings import KeycloakSettings

PROTECTED_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
_DEFAULT_ORIGIN = "http://localhost"
MCP_REQUIRED_SCOPES: tuple[str, ...] = ("openid",)


def inserted_protected_resource_metadata_path(mcp_path: str) -> str:
    """Return the RFC9728 path-inserted protected-resource metadata URI."""
    return f"{PROTECTED_RESOURCE_METADATA_PATH}{mcp_path.rstrip('/') or '/'}"


def is_mcp_path(path: str, mcp_path: str) -> bool:
    """Return True when *path* targets the configured MCP HTTP surface."""
    return path == mcp_path or path.startswith(f"{mcp_path}/")


def origin_from_scope(scope: dict[str, Any]) -> str:
    """Build a best-effort request origin from an ASGI scope."""
    headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in scope.get("headers", [])
    }

    scheme = headers.get("x-forwarded-proto") or scope.get("scheme") or "http"
    host = headers.get("x-forwarded-host") or headers.get("host")
    if host:
        return f"{scheme}://{host}"

    server = scope.get("server")
    if isinstance(server, tuple) and len(server) >= 2:
        server_host, server_port = server[0], server[1]
        if isinstance(server_host, str) and server_host:
            default_port = 443 if scheme == "https" else 80
            if isinstance(server_port, int) and server_port != default_port:
                return f"{scheme}://{server_host}:{server_port}"
            return f"{scheme}://{server_host}"

    return _DEFAULT_ORIGIN


def build_protected_resource_metadata(origin: str, mcp_path: str) -> dict[str, object]:
    """Return the OAuth protected-resource metadata document for MCP clients."""
    clean_origin = origin.rstrip("/") or _DEFAULT_ORIGIN
    keycloak_settings = KeycloakSettings()
    return {
        "resource": f"{clean_origin}{mcp_path}",
        "authorization_servers": [keycloak_settings.public_issuer],
        "scopes_supported": list(MCP_REQUIRED_SCOPES),
    }


def build_www_authenticate_header(
    origin: str,
    *,
    error: str | None = None,
    error_description: str | None = None,
) -> str:
    """Build a Bearer challenge that advertises the MCP auth metadata URL."""
    clean_origin = origin.rstrip("/") or _DEFAULT_ORIGIN
    parts = [
        'Bearer realm="contextiq-mcp"',
        f'resource_metadata="{clean_origin}{PROTECTED_RESOURCE_METADATA_PATH}"',
        f'scope="{" ".join(MCP_REQUIRED_SCOPES)}"',
    ]
    if error is not None:
        parts.append(f'error="{error}"')
    if error_description is not None:
        escaped = error_description.replace('"', "'")
        parts.append(f'error_description="{escaped}"')
    return ", ".join(parts)