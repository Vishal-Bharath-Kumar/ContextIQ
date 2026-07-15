"""
Keycloak connection settings for the MCP Gateway — TASK-US043-03.

All values are read from environment variables with the KEYCLOAK_ prefix.
No hard-coded URLs or algorithms (OWASP A05 — Security Misconfiguration).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KeycloakSettings(BaseSettings):
    """
    Keycloak OIDC connection parameters.

    Example .env / environment:
      KEYCLOAK_URL=https://contextiq.internal/auth
      KEYCLOAK_REALM=contextiq
      KEYCLOAK_AUDIENCE=contextiq-mcp-gateway
      KEYCLOAK_ALGORITHMS=RS256
    """

    model_config = SettingsConfigDict(
        env_prefix="KEYCLOAK_",
        env_file=".env",
        extra="ignore",
    )

    url:        str       = "http://keycloak.keycloak.svc.cluster.local/auth"
    realm:      str       = "contextiq"
    audience:   str       = "contextiq-mcp-gateway"
    algorithms: list[str] = ["RS256"]

    @property
    def jwks_uri(self) -> str:
        """Full URI for Keycloak's JWKS endpoint."""
        return f"{self.url}/realms/{self.realm}/protocol/openid-connect/certs"

    @property
    def issuer(self) -> str:
        """Expected `iss` claim value for tokens issued by this realm."""
        return f"{self.url}/realms/{self.realm}"
