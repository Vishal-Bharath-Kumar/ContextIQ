"""
Registers a SAML 2.0 identity provider in the contextiq realm.
Attribute mappers translate SAML assertion attributes to Keycloak realm roles.

Run after bootstrap_realm.py has created the contextiq realm and its platform roles
and after configure_entra_id_broker.py has verified idp_config.yaml is present.

Required env vars — read from Vault; never hard-coded (OWASP A02):
  KEYCLOAK_URL              https://contextiq.internal/auth
  KEYCLOAK_ADMIN_USER       (from Vault)
  KEYCLOAK_ADMIN_PASSWORD   (from Vault)
  SAML_IDP_ENTITY_ID        Entity ID of the on-premises IdP (from Vault)
  SAML_IDP_SSO_URL          SSO redirect binding URL of the on-premises IdP (from Vault)
  SAML_IDP_SIGNING_CERT     Base64-encoded DER certificate, no PEM headers (from Vault)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from keycloak import KeycloakAdmin

REALM = "contextiq"
IDP_ALIAS = "saml-onprem"
CONFIG_PATH = Path(__file__).parent / "idp_config.yaml"


def get_admin_client() -> KeycloakAdmin:
    return KeycloakAdmin(
        server_url=os.environ["KEYCLOAK_URL"],
        username=os.environ["KEYCLOAK_ADMIN_USER"],
        password=os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        realm_name=REALM,
        verify=True,
    )


def register_saml_broker(admin: KeycloakAdmin) -> None:
    """
    AC-7: Create (or update) a SAML 2.0 identity provider in the contextiq realm.

    Keycloak acts as the SAML SP; the on-prem directory server is the SAML IdP.
    Idempotent: re-running calls update_idp if the alias already exists.
    """
    entity_id = os.environ["SAML_IDP_ENTITY_ID"]
    sso_url = os.environ["SAML_IDP_SSO_URL"]
    signing_cert = os.environ["SAML_IDP_SIGNING_CERT"]

    idp_payload: dict[str, Any] = {
        "alias": IDP_ALIAS,
        "displayName": "On-Premises IdP (SAML 2.0)",
        "providerId": "saml",
        "enabled": True,
        "trustEmail": True,
        "storeToken": False,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": {
            # SAML IdP metadata — injected from Vault at deploy time
            "entityId": entity_id,
            "singleSignOnServiceUrl": sso_url,
            "nameIDPolicyFormat": "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
            "principalType": "ATTRIBUTE",
            "principalAttribute": "uid",
            # Signing / encryption
            "signingCertificate": signing_cert,
            "validateSignature": "true",
            "wantAssertionsSigned": "true",
            "wantAssertionsEncrypted": "false",
            # POST binding for all SAML messages
            "postBindingResponse": "true",
            "postBindingAuthnRequest": "true",
            "postBindingLogout": "true",
            "forceAuthn": "false",
            # AC-7: Re-evaluate role mappings on every SAML login
            "syncMode": "FORCE",
        },
    }

    existing_aliases = [idp["alias"] for idp in admin.get_idps()]
    if IDP_ALIAS in existing_aliases:
        admin.update_idp(IDP_ALIAS, idp_payload)
        print(f"SAML IdP '{IDP_ALIAS}' updated.")
    else:
        admin.create_idp(idp_payload)
        print(f"SAML IdP '{IDP_ALIAS}' created.")


def _upsert_mapper(admin: KeycloakAdmin, mapper: dict[str, Any]) -> None:
    """
    Create or update a single IdP attribute mapper.

    BUG FIX (spec): the spec's implementation was "create if not exists" only —
    if a mapping configuration changes, re-running the script silently kept the
    stale mapper.  A true upsert must retrieve the existing mapper's `id` and
    call update_mapper_in_idp when the name already exists.
    """
    existing: list[dict[str, Any]] = admin.get_idp_mappers(IDP_ALIAS)
    match = next((m for m in existing if m["name"] == mapper["name"]), None)
    if match is not None:
        # Update in-place; Keycloak requires the mapper id on updates
        admin.update_mapper_in_idp(IDP_ALIAS, match["id"], mapper)
    else:
        admin.add_mapper_to_idp(IDP_ALIAS, mapper)


def configure_saml_attribute_role_mappers(admin: KeycloakAdmin) -> None:
    """
    AC-7: Map SAML assertion attributes to Keycloak realm roles.

    Uses the same `group_role_mappings` table from idp_config.yaml so the
    Entra ID OIDC broker and the SAML broker share one authoritative mapping
    source (DRY principle).

    The SAML `saml-role-idp-mapper` type reads a named assertion attribute
    and grants the mapped realm role when the attribute value matches.
    On-prem IdPs typically expose group membership as a multi-valued `Role`
    or `memberOf` attribute; the Entra group display names (e.g.
    "ContextIQ-Auditors") are reused as the expected attribute values so that
    a single idp_config.yaml drives both federation paths.
    """
    config: dict[str, Any] = yaml.safe_load(CONFIG_PATH.read_text())
    mappings: list[dict[str, Any]] = config["group_role_mappings"]

    for entry in mappings:
        saml_attribute_value: str = entry["entra_group"]   # shared attribute value
        keycloak_role: str = entry["keycloak_role"]
        mapper_name: str = f"saml-role-{keycloak_role}"

        mapper: dict[str, Any] = {
            "name": mapper_name,
            "identityProviderMapper": "saml-role-idp-mapper",
            "identityProviderAlias": IDP_ALIAS,
            "config": {
                "syncMode": "INHERIT",
                "attribute": "Role",                    # SAML assertion attribute name
                "attribute.value": saml_attribute_value,
                "role": keycloak_role,
            },
        }
        _upsert_mapper(admin, mapper)
        print(
            f"  SAML mapper '{mapper_name}' upserted "
            f"({saml_attribute_value} → {keycloak_role})"
        )


def print_sp_metadata_endpoint() -> None:
    """
    Print the SP metadata URL for the on-premises IdP administrator.

    The IdP admin registers ContextIQ as a trusted SAML Service Provider by
    importing the metadata returned from this URL.
    """
    base = os.environ["KEYCLOAK_URL"]
    sp_metadata_url = f"{base}/realms/{REALM}/protocol/saml/descriptor"
    print(f"\nSAML SP metadata endpoint (share with your IdP admin):\n  {sp_metadata_url}\n")


def main() -> None:
    admin = get_admin_client()
    register_saml_broker(admin)
    configure_saml_attribute_role_mappers(admin)
    print_sp_metadata_endpoint()
    print("SAML 2.0 federation configuration complete.")


if __name__ == "__main__":
    main()
