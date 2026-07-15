"""
Registers Microsoft Entra ID as an OIDC identity provider in the contextiq realm.
Configures a groups claim mapper and per-group realm-role mappers.

Run after bootstrap_realm.py has created the contextiq realm and its platform roles.

Required env vars — read from Vault; never hard-coded:
  KEYCLOAK_URL              https://contextiq.internal/auth
  KEYCLOAK_ADMIN_USER       Keycloak master-realm admin username
  KEYCLOAK_ADMIN_PASSWORD   Keycloak master-realm admin password
  ENTRA_CLIENT_ID           Entra App Registration client_id
  ENTRA_CLIENT_SECRET       Entra App Registration client_secret
  ENTRA_TENANT_ID           Entra directory / tenant ID
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from keycloak import KeycloakAdmin  # python-keycloak>=3.0

REALM       = "contextiq"
IDP_ALIAS   = "entra-id"
CONFIG_PATH = Path(__file__).parent / "idp_config.yaml"


def get_admin_client() -> KeycloakAdmin:
    # BUG FIX: authenticate against master realm (master-realm admin credentials
    # cannot log in to a non-master realm).  Then switch the working realm to
    # REALM — consistent with bootstrap_realm.py.
    admin = KeycloakAdmin(
        server_url=os.environ["KEYCLOAK_URL"],
        username=os.environ["KEYCLOAK_ADMIN_USER"],
        password=os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        realm_name="master",
        verify=True,
    )
    admin.realm_name = REALM
    return admin


def register_entra_id_broker(admin: KeycloakAdmin) -> None:
    """
    Creates or updates the Entra ID OIDC identity provider in Keycloak.
    AC-2: identity brokering configured for Entra ID via OIDC.
    """
    tenant_id     = os.environ["ENTRA_TENANT_ID"]
    client_id     = os.environ["ENTRA_CLIENT_ID"]
    client_secret = os.environ["ENTRA_CLIENT_SECRET"]

    idp_payload: dict[str, Any] = {
        "alias":                    IDP_ALIAS,
        "displayName":              "Microsoft Entra ID",
        "providerId":               "oidc",
        "enabled":                  True,
        "trustEmail":               True,
        "storeToken":               False,
        "addReadTokenRoleOnCreate": False,
        # first broker login flow handles new-user provisioning
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": {
            # Entra ID v2 OIDC endpoints
            "issuer":           f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "authorizationUrl": f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
            "tokenUrl":         f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            "jwksUrl":          f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
            "userInfoUrl":      "https://graph.microsoft.com/oidc/userinfo",
            "logoutUrl":        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/logout",
            "clientId":         client_id,
            "clientSecret":     client_secret,
            # Request groups claim so the group-to-role mappers can read it.
            "defaultScope":     "openid profile email groups",
            "clientAuthMethod": "client_secret_post",
            # AC-4: re-evaluate role assignment on every login, not only first login.
            "syncMode":         "FORCE",
            "validateSignature": "true",
            "useJwksUrl":       "true",
        },
    }

    existing_aliases: list[str] = [idp["alias"] for idp in admin.get_idps()]
    if IDP_ALIAS in existing_aliases:
        admin.update_idp(IDP_ALIAS, idp_payload)
        print(f"IdP '{IDP_ALIAS}' updated.")
    else:
        admin.create_idp(idp_payload)
        print(f"IdP '{IDP_ALIAS}' created.")


def _create_mapper(
    admin: KeycloakAdmin,
    idp_alias: str,
    mapper: dict[str, Any],
) -> None:
    """Idempotent mapper creation — skips if a mapper with the same name exists."""
    existing: list[dict[str, Any]] = admin.get_idp_mappers(idp_alias)
    existing_names = [m["name"] for m in existing]
    if mapper["name"] not in existing_names:
        admin.add_mapper_to_idp(idp_alias, mapper)


def configure_group_role_mappers(admin: KeycloakAdmin) -> None:
    """
    AC-4: For each Entra ID group → Keycloak role mapping in idp_config.yaml,
    creates:
      1. A single claim-extractor mapper that copies the `groups` array claim
         from the Entra ID token into the `entra_groups` user attribute.
      2. One `oidc-role-idp-mapper` per group that assigns the matching realm
         role when the `groups` claim contains the configured group name.

    syncMode=INHERIT inherits FORCE from the IdP config (AC-4).
    """
    raw: dict[str, Any] = yaml.safe_load(CONFIG_PATH.read_text())
    mappings: list[dict[str, str]] = raw["group_role_mappings"]

    # BUG FIX: claim extractor moved BEFORE the loop — it only needs to be
    # created once, not rechecked on every group iteration.
    # Extracts the `groups` array claim from the Entra ID ID token and stores
    # it as the `entra_groups` user attribute for downstream reference.
    claim_mapper: dict[str, Any] = {
        "name": "claim-groups",   # BUG FIX: was f"claim-groups" (unused f-string)
        "identityProviderMapper": "oidc-user-attribute-idp-mapper",
        "identityProviderAlias": IDP_ALIAS,
        "config": {
            "syncMode":       "INHERIT",
            "claim":          "groups",
            "user.attribute": "entra_groups",
        },
    }
    _create_mapper(admin, IDP_ALIAS, claim_mapper)

    for entry in mappings:
        entra_group   = entry["entra_group"]
        keycloak_role = entry["keycloak_role"]
        mapper_name   = f"groups-to-{keycloak_role}"

        # BUG FIX: was 'oidc-group-idp-mapper' which maps users into Keycloak
        # groups (not roles).  'oidc-role-idp-mapper' is the correct type for
        # assigning a realm role when a specific claim value is present.
        #
        # BUG FIX: config keys 'group' and 'attribute.name' are wrong for this
        # mapper type.  Correct keys: 'claim' (the claim field) and
        # 'claim.value' (the value that must be present to trigger role assignment).
        role_mapper: dict[str, Any] = {
            "name": mapper_name,
            "identityProviderMapper": "oidc-role-idp-mapper",
            "identityProviderAlias": IDP_ALIAS,
            "config": {
                "syncMode":    "INHERIT",
                "claim":       "groups",
                "claim.value": entra_group,
                "role":        keycloak_role,
            },
        }
        _create_mapper(admin, IDP_ALIAS, role_mapper)
        print(f"  Mapper '{mapper_name}' configured ({entra_group} → {keycloak_role})")


def configure_email_claim_mapper(admin: KeycloakAdmin) -> None:
    """Map Entra ID `email` and `preferred_username` claims to Keycloak user fields."""
    standard_mappers: list[dict[str, Any]] = [
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
    ]
    for mapper in standard_mappers:
        _create_mapper(admin, IDP_ALIAS, mapper)


def main() -> None:
    admin = get_admin_client()
    register_entra_id_broker(admin)
    configure_group_role_mappers(admin)
    configure_email_claim_mapper(admin)
    print("Entra ID OIDC broker configuration complete.")


if __name__ == "__main__":
    main()
