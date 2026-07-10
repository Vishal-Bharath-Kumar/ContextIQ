# TASK-US043-02 — Entra ID OIDC Identity Broker and Group-to-Role Mapper

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US043-02 |
| User Story | US-043 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Configure Keycloak as an identity broker for Microsoft Entra ID (formerly Azure AD) using OIDC (AC-2). Set up an `IdentityProvider` in the `contextiq` realm that delegates authentication to Entra ID's OIDC endpoints and, on first/subsequent login, maps Entra ID security group membership to the corresponding Keycloak realm roles (AC-4). All configuration is expressed as idempotent Python scripts using `python-keycloak>=3.0` so it can be applied by CI against any environment.

## Implementation Details

**Technology:** Keycloak 24.x Admin REST API, `python-keycloak>=3.0`, Entra ID OIDC

**File locations:**
- `scripts/keycloak/configure_entra_id_broker.py` — IdP registration + group mapper
- `scripts/keycloak/idp_config.yaml` — role-to-group mapping table (non-sensitive)
- `k8s/keycloak/entra-id-secret.yaml` — placeholder Secret for Entra ID client credentials

---

### Role-to-group mapping table (non-sensitive config)

```yaml
# scripts/keycloak/idp_config.yaml
# Maps Entra ID security group display names to ContextIQ platform roles.
# Group names are matched against the `groups` claim in the Entra ID ID token.
group_role_mappings:
  - entra_group: "ContextIQ-Admins"
    keycloak_role: "admin"
  - entra_group: "ContextIQ-PlatformEngineers"
    keycloak_role: "platform_engineer"
  - entra_group: "ContextIQ-SecurityOfficers"
    keycloak_role: "security_officer"
  - entra_group: "ContextIQ-Developers"
    keycloak_role: "developer"
  - entra_group: "ContextIQ-Managers"
    keycloak_role: "manager"
  - entra_group: "ContextIQ-Auditors"
    keycloak_role: "auditor"
  - entra_group: "ContextIQ-DevOpsSRE"
    keycloak_role: "devops_sre"
```

---

### Entra ID client credentials secret (placeholder — injected by Vault at runtime)

```yaml
# k8s/keycloak/entra-id-secret.yaml
# IMPORTANT: Real values injected by Vault Agent at runtime.
# NEVER commit actual client_id or client_secret to version control.
apiVersion: v1
kind: Secret
metadata:
  name: entra-id-oidc-credentials
  namespace: keycloak
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "keycloak"
    vault.hashicorp.com/agent-inject-secret-entra: "contextiq/data/keycloak/entra_id"
type: Opaque
stringData:
  ENTRA_CLIENT_ID:     "PLACEHOLDER"
  ENTRA_CLIENT_SECRET: "PLACEHOLDER"
  ENTRA_TENANT_ID:     "PLACEHOLDER"
```

---

### Entra ID OIDC broker configuration script

```python
# scripts/keycloak/configure_entra_id_broker.py
"""
Registers Microsoft Entra ID as an OIDC identity provider in the contextiq realm.
Configures a groups claim mapper and per-group role mappers.

Required env vars:
  KEYCLOAK_URL              https://contextiq.internal/auth
  KEYCLOAK_ADMIN_USER       (from Vault)
  KEYCLOAK_ADMIN_PASSWORD   (from Vault)
  ENTRA_CLIENT_ID           (from Vault — Entra App Registration client_id)
  ENTRA_CLIENT_SECRET       (from Vault — Entra App Registration client_secret)
  ENTRA_TENANT_ID           (Entra directory / tenant ID)
"""
from __future__ import annotations
import os
import yaml
from pathlib  import Path
from keycloak import KeycloakAdmin

REALM        = "contextiq"
IDP_ALIAS    = "entra-id"
CONFIG_PATH  = Path(__file__).parent / "idp_config.yaml"


def get_admin_client() -> KeycloakAdmin:
    return KeycloakAdmin(
        server_url = os.environ["KEYCLOAK_URL"],
        username   = os.environ["KEYCLOAK_ADMIN_USER"],
        password   = os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        realm_name = REALM,
        verify     = True,
    )


def register_entra_id_broker(admin: KeycloakAdmin) -> str:
    """
    Creates the Entra ID OIDC identity provider in Keycloak.
    Returns the IDP internal ID.
    AC-2: identity brokering configured for Entra ID via OIDC.
    """
    tenant_id     = os.environ["ENTRA_TENANT_ID"]
    client_id     = os.environ["ENTRA_CLIENT_ID"]
    client_secret = os.environ["ENTRA_CLIENT_SECRET"]

    idp_payload = {
        "alias":                     IDP_ALIAS,
        "displayName":               "Microsoft Entra ID",
        "providerId":                "oidc",
        "enabled":                   True,
        "trustEmail":                True,
        "storeToken":                False,
        "addReadTokenRoleOnCreate":  False,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": {
            # Entra ID v2 OIDC endpoints
            "issuer":                f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "authorizationUrl":      f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
            "tokenUrl":              f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            "jwksUrl":               f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
            "userInfoUrl":           "https://graph.microsoft.com/oidc/userinfo",
            "logoutUrl":             f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/logout",
            "clientId":              client_id,
            "clientSecret":          client_secret,
            # Request groups claim so group mapper can read it
            "defaultScope":          "openid profile email groups",
            "clientAuthMethod":      "client_secret_post",
            "syncMode":              "FORCE",   # AC-4: re-sync roles on every login
            "validateSignature":     "true",
            "useJwksUrl":            "true",
        },
    }

    existing_idps = [idp["alias"] for idp in admin.get_idps()]
    if IDP_ALIAS in existing_idps:
        admin.update_idp(IDP_ALIAS, idp_payload)
        print(f"IdP '{IDP_ALIAS}' updated.")
    else:
        admin.create_idp(idp_payload)
        print(f"IdP '{IDP_ALIAS}' created.")

    return IDP_ALIAS


def _create_mapper(admin: KeycloakAdmin, idp_alias: str, mapper: dict) -> None:
    existing = admin.get_idp_mappers(idp_alias)
    names    = [m["name"] for m in existing]
    if mapper["name"] not in names:
        admin.add_mapper_to_idp(idp_alias, mapper)


def configure_group_role_mappers(admin: KeycloakAdmin) -> None:
    """
    AC-4: For each Entra ID group → Keycloak role mapping in idp_config.yaml,
    create a 'oidc-group-idp-mapper' so that Entra ID group membership is
    automatically converted to a Keycloak realm role assignment on every login.

    Mapper type: 'oidc-hardcoded-role-idp-mapper' assigns a specific realm role
    to all users authenticated via this IdP when the groups claim contains the
    configured Entra group name.
    """
    config: dict = yaml.safe_load(CONFIG_PATH.read_text())
    mappings: list[dict] = config["group_role_mappings"]

    for entry in mappings:
        entra_group    = entry["entra_group"]
        keycloak_role  = entry["keycloak_role"]
        mapper_name    = f"groups-to-{keycloak_role}"

        # Mapper 1: extract `groups` claim from Entra ID token
        claim_mapper = {
            "name":            f"claim-groups",
            "identityProviderMapper": "oidc-user-attribute-idp-mapper",
            "identityProviderAlias": IDP_ALIAS,
            "config": {
                "syncMode":    "INHERIT",
                "claim":       "groups",
                "user.attribute": "entra_groups",
            },
        }
        _create_mapper(admin, IDP_ALIAS, claim_mapper)

        # Mapper 2: map Entra group name → realm role
        role_mapper = {
            "name":            mapper_name,
            "identityProviderMapper": "oidc-group-idp-mapper",
            "identityProviderAlias": IDP_ALIAS,
            "config": {
                "syncMode":       "INHERIT",
                "group":          entra_group,
                "role":           keycloak_role,  # Keycloak realm role name
                "attribute.name": "groups",       # claim field to match against
            },
        }
        _create_mapper(admin, IDP_ALIAS, role_mapper)
        print(f"  Mapper '{mapper_name}' configured ({entra_group} → {keycloak_role})")


def configure_email_claim_mapper(admin: KeycloakAdmin) -> None:
    """Map Entra ID 'email' and 'preferred_username' claims to Keycloak user fields."""
    for mapper in [
        {
            "name": "entra-email",
            "identityProviderMapper": "oidc-user-attribute-idp-mapper",
            "identityProviderAlias": IDP_ALIAS,
            "config": {
                "syncMode":       "INHERIT",
                "claim":          "email",
                "user.attribute": "email",
            },
        },
        {
            "name": "entra-preferred-username",
            "identityProviderMapper": "oidc-user-attribute-idp-mapper",
            "identityProviderAlias": IDP_ALIAS,
            "config": {
                "syncMode":       "INHERIT",
                "claim":          "preferred_username",
                "user.attribute": "username",
            },
        },
    ]:
        _create_mapper(admin, IDP_ALIAS, mapper)


def main() -> None:
    admin = get_admin_client()
    register_entra_id_broker(admin)
    configure_group_role_mappers(admin)
    configure_email_claim_mapper(admin)
    print("Entra ID OIDC broker configuration complete.")


if __name__ == "__main__":
    main()
```

## Acceptance Criteria

- [ ] `configure_entra_id_broker.py` runs idempotently — re-running with same config produces no duplicates (AC-2)
- [ ] Keycloak Admin Console shows the `entra-id` identity provider in the `contextiq` realm (AC-2)
- [ ] A test user in the Entra ID `ContextIQ-Admins` group logs in via the `/auth` endpoint and receives a Keycloak JWT containing `realm_access.roles: ["admin"]` (AC-4)
- [ ] `syncMode: FORCE` means role assignment is re-evaluated on every login, not only on first login (AC-4)
- [ ] `idp_config.yaml` covers all 7 `PlatformRole` values (AC-4)
- [ ] `entra-id-secret.yaml` contains no real credentials — values are `PLACEHOLDER` (OWASP A02)

## Dependencies

- TASK-US043-01 — `contextiq` realm with PlatformRole realm roles must exist before running this script
- EP-DATA-001 — Vault path `contextiq/data/keycloak/entra_id` must be populated with Entra App Registration credentials
- TASK-US042-01 — Entra group names in `idp_config.yaml` must mirror the 7 `PlatformRole` values

## Definition of Done

- [ ] `python scripts/keycloak/configure_entra_id_broker.py` completes without error against staging Keycloak
- [ ] Manual login test: Entra ID user mapped to `ContextIQ-SecurityOfficers` group receives `security_officer` role in their Keycloak JWT
- [ ] `mypy --strict scripts/keycloak/configure_entra_id_broker.py` passes
