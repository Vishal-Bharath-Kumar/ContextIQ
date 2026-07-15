"""
One-time realm creation script for ContextIQ.

Run inside the cluster (or with KEYCLOAK_URL pointing at the admin endpoint)
after the Keycloak Deployment is fully ready.

Required env vars — read from Vault; never hard-coded:
  KEYCLOAK_URL              https://contextiq.internal/auth
  KEYCLOAK_ADMIN_USER       Keycloak master-realm admin username
  KEYCLOAK_ADMIN_PASSWORD   Keycloak master-realm admin password
"""
from __future__ import annotations

import os

from keycloak import KeycloakAdmin  # python-keycloak>=3.0

REALM = "contextiq"

PLATFORM_ROLES: list[str] = [
    "developer",
    "platform_engineer",
    "devops_sre",
    "admin",
    "security_officer",
    "manager",
    "auditor",
]


def get_admin_client() -> KeycloakAdmin:
    url      = os.environ["KEYCLOAK_URL"]
    username = os.environ["KEYCLOAK_ADMIN_USER"]
    password = os.environ["KEYCLOAK_ADMIN_PASSWORD"]
    return KeycloakAdmin(
        server_url=url,
        username=username,
        password=password,
        realm_name="master",
        verify=True,
    )


def bootstrap(admin: KeycloakAdmin) -> None:
    # ── Realm ──────────────────────────────────────────────────────────────
    existing: list[str] = [r["realm"] for r in admin.get_realms()]
    if REALM not in existing:
        admin.create_realm(
            payload={
                "realm":                  REALM,
                "enabled":                True,
                "displayName":            "ContextIQ",
                # Token lifetimes — AC-6
                "accessTokenLifespan":    300,    # 5 min
                "ssoSessionMaxLifespan":  28800,  # 8 h (refresh-token TTL)
                "ssoSessionIdleTimeout":  1800,   # 30 min idle
                "accessCodeLifespan":     60,
                # Security hardening
                "bruteForceProtected":    True,
                "permanentLockout":       False,
                "loginWithEmailAllowed":  True,
                "duplicateEmailsAllowed": False,
                "resetPasswordAllowed":   True,
                "editUsernameAllowed":    False,
            },
            skip_exists=True,
        )
        print(f"Realm '{REALM}' created.")
    else:
        print(f"Realm '{REALM}' already exists — skipping creation.")

    # ── Platform roles (mirror PlatformRole StrEnum — TASK-US042-01) ───────
    admin.realm_name = REALM
    for role in PLATFORM_ROLES:
        admin.create_realm_role({"name": role}, skip_exists=True)
    print(f"Realm roles created: {', '.join(PLATFORM_ROLES)}")

    # ── MCP Gateway OIDC client ─────────────────────────────────────────────
    admin.create_client(
        payload={
            "clientId":                    "contextiq-mcp-gateway",
            "enabled":                     True,
            "protocol":                    "openid-connect",
            "publicClient":                False,
            "authorizationServicesEnabled": False,
            "directAccessGrantsEnabled":   False,
            "standardFlowEnabled":         True,
            "implicitFlowEnabled":         False,
        },
        skip_exists=True,
    )
    print("MCP Gateway client created.")


if __name__ == "__main__":
    _admin = get_admin_client()
    bootstrap(_admin)
