"""
Keycloak connection settings for the MCP Gateway — TASK-US043-03.

All values are read from environment variables with the KEYCLOAK_ prefix.
No hard-coded URLs or algorithms (OWASP A05 — Security Misconfiguration).
"""
from __future__ import annotations

from urllib.parse import urljoin

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
    public_url: str | None = None
    realm:      str       = "contextiq"
    audience:   str       = "contextiq-mcp-gateway"
    algorithms: list[str] = ["RS256"]

    # Confidential client credentials — only required by the local-dev
    # password-grant login route (src/auth/dev_login.py). Never set/used in
    # production, which relies on the full browser-redirect OIDC flow instead.
    client_id:     str = "contextiq-mcp-gateway"
    client_secret: str = ""

    @property
    def jwks_uri(self) -> str:
        """Full URI for Keycloak's JWKS endpoint."""
        return f"{self.url}/realms/{self.realm}/protocol/openid-connect/certs"

    @property
    def issuer(self) -> str:
        """Expected `iss` claim value for tokens issued by this realm."""
        return f"{self.url}/realms/{self.realm}"

    @property
    def public_issuer(self) -> str:
        """Browser-reachable issuer for OAuth discovery metadata."""
        base_url = self.public_url or self.url
        return f"{base_url}/realms/{self.realm}"

    @property
    def authorization_endpoint(self) -> str:
        """Browser-reachable authorization endpoint."""
        return f"{self.public_issuer}/protocol/openid-connect/auth"

    @property
    def public_token_uri(self) -> str:
        """Browser-reachable token endpoint."""
        return f"{self.public_issuer}/protocol/openid-connect/token"

    @property
    def public_revocation_endpoint(self) -> str:
        """Browser-reachable revocation endpoint."""
        return f"{self.public_issuer}/protocol/openid-connect/revoke"

    @property
    def revocation_endpoint(self) -> str:
        """Internal revocation endpoint reachable from the API container."""
        return f"{self.issuer}/protocol/openid-connect/revoke"

    @property
    def openid_configuration_uri(self) -> str:
        """Browser-reachable OIDC discovery document."""
        return urljoin(f"{self.public_issuer}/", ".well-known/openid-configuration")

    @property
    def internal_openid_configuration_uri(self) -> str:
        """OIDC discovery document reachable from the API container."""
        return urljoin(f"{self.issuer}/", ".well-known/openid-configuration")

    @property
    def token_uri(self) -> str:
        """Full URI for Keycloak's token endpoint (password/client_credentials grants)."""
        return f"{self.url}/realms/{self.realm}/protocol/openid-connect/token"
