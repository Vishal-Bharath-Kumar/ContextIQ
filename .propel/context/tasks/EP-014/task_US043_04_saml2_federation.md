# TASK-US043-04 — SAML 2.0 Federation for On-Premises Identity Providers

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US043-04 |
| User Story | US-043 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Infrastructure / Backend |
| Priority | P1 |
| Points | 2 |
| Status | Draft |

## Description

Configure Keycloak as a SAML 2.0 Service Provider (SP) that can federate with on-premises identity providers (AC-7). The SAML broker is defined in parallel to the Entra ID OIDC broker (TASK-US043-02) — both are configured in the `contextiq` Keycloak realm. An attribute mapper translates SAML assertion attributes (`Role` or `memberOf`) to Keycloak realm roles using the same `group_role_mappings` table from TASK-US043-02. The Keycloak SP metadata endpoint (`/realms/contextiq/protocol/saml/descriptor`) provides the XML metadata that the on-premises IdP administrator uses to register ContextIQ as a trusted SP.

## Implementation Details

**Technology:** Keycloak 24.x SAML IdP configuration, `python-keycloak>=3.0`, SAML 2.0

**File locations:**
- `scripts/keycloak/configure_saml_broker.py` — SAML IdP registration + attribute-to-role mappers
- `scripts/keycloak/saml_idp_metadata.xml.template` — placeholder SP metadata template (documentation aid)
- `k8s/keycloak/saml-idp-secret.yaml` — placeholder Secret for SAML IdP signing certificate

---

### SAML IdP certificate secret (placeholder)

```yaml
# k8s/keycloak/saml-idp-secret.yaml
# IMPORTANT: Contains no real certificate data — actual PEM content injected
# by Vault Agent at runtime.
# NEVER commit a real certificate or private key to version control.
apiVersion: v1
kind: Secret
metadata:
  name: saml-idp-certificate
  namespace: keycloak
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "keycloak"
    vault.hashicorp.com/agent-inject-secret-saml: "contextiq/data/keycloak/saml_idp"
type: Opaque
stringData:
  SAML_IDP_ENTITY_ID:       "PLACEHOLDER"
  SAML_IDP_SSO_URL:         "PLACEHOLDER"
  SAML_IDP_SIGNING_CERT:    "PLACEHOLDER"   # PEM-encoded X.509, no headers/footers
```

---

### SAML broker configuration script

```python
# scripts/keycloak/configure_saml_broker.py
"""
Registers a SAML 2.0 identity provider in the contextiq realm.
Attribute mappers translate SAML assertion attributes to Keycloak realm roles.

Required env vars:
  KEYCLOAK_URL              https://contextiq.internal/auth
  KEYCLOAK_ADMIN_USER       (from Vault)
  KEYCLOAK_ADMIN_PASSWORD   (from Vault)
  SAML_IDP_ENTITY_ID        Entity ID of the on-premises IdP (from Vault)
  SAML_IDP_SSO_URL          SSO redirect binding URL of the on-premises IdP (from Vault)
  SAML_IDP_SIGNING_CERT     Base64-encoded DER certificate (no PEM headers, from Vault)
"""
from __future__ import annotations
import os
import yaml
from pathlib  import Path
from keycloak import KeycloakAdmin

REALM      = "contextiq"
IDP_ALIAS  = "saml-onprem"
CONFIG_PATH = Path(__file__).parent / "idp_config.yaml"


def get_admin_client() -> KeycloakAdmin:
    return KeycloakAdmin(
        server_url = os.environ["KEYCLOAK_URL"],
        username   = os.environ["KEYCLOAK_ADMIN_USER"],
        password   = os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        realm_name = REALM,
        verify     = True,
    )


def register_saml_broker(admin: KeycloakAdmin) -> None:
    """
    AC-7: Create a SAML 2.0 identity provider in the contextiq realm.
    Keycloak acts as the SAML SP; the on-prem IdP is the SAML IdP.
    """
    entity_id    = os.environ["SAML_IDP_ENTITY_ID"]
    sso_url      = os.environ["SAML_IDP_SSO_URL"]
    signing_cert = os.environ["SAML_IDP_SIGNING_CERT"]

    idp_payload = {
        "alias":                     IDP_ALIAS,
        "displayName":               "On-Premises IdP (SAML 2.0)",
        "providerId":                "saml",
        "enabled":                   True,
        "trustEmail":                True,
        "storeToken":                False,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": {
            # SAML IdP metadata
            "entityId":                      entity_id,
            "singleSignOnServiceUrl":        sso_url,
            "nameIDPolicyFormat":            "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
            "principalType":                 "ATTRIBUTE",
            "principalAttribute":            "uid",
            # Signing / encryption
            "signingCertificate":            signing_cert,
            "validateSignature":             "true",
            "wantAssertionsSigned":          "true",
            "wantAssertionsEncrypted":       "false",
            # Binding
            "postBindingResponse":           "true",
            "postBindingAuthnRequest":       "true",
            "postBindingLogout":             "true",
            "forceAuthn":                    "false",
            # Sync — re-evaluate role mappings on every login
            "syncMode":                      "FORCE",
        },
    }

    existing_idps = [idp["alias"] for idp in admin.get_idps()]
    if IDP_ALIAS in existing_idps:
        admin.update_idp(IDP_ALIAS, idp_payload)
        print(f"SAML IdP '{IDP_ALIAS}' updated.")
    else:
        admin.create_idp(idp_payload)
        print(f"SAML IdP '{IDP_ALIAS}' created.")


def _upsert_mapper(admin: KeycloakAdmin, mapper: dict) -> None:
    existing = admin.get_idp_mappers(IDP_ALIAS)
    names    = [m["name"] for m in existing]
    if mapper["name"] not in names:
        admin.add_mapper_to_idp(IDP_ALIAS, mapper)


def configure_saml_attribute_role_mappers(admin: KeycloakAdmin) -> None:
    """
    AC-7: Map SAML assertion attributes (e.g. 'Role' or 'memberOf') to
    Keycloak realm roles using the same group_role_mappings from idp_config.yaml.

    SAML `saml-role-idp-mapper` type:
      - Reads a named attribute from the SAML assertion
      - If the attribute value matches `attribute.value`, assigns `role` to the user
    """
    config: dict = yaml.safe_load(CONFIG_PATH.read_text())
    mappings: list[dict] = config["group_role_mappings"]

    for entry in mappings:
        # On-prem SAML IdPs commonly send group membership via a 'Role' or
        # 'memberOf' multi-value attribute. We use the Entra group name as the
        # attribute value to keep the mapping table unified.
        saml_attribute_value = entry["entra_group"]   # reuse same group names
        keycloak_role        = entry["keycloak_role"]
        mapper_name          = f"saml-role-{keycloak_role}"

        mapper = {
            "name":            mapper_name,
            "identityProviderMapper": "saml-role-idp-mapper",
            "identityProviderAlias": IDP_ALIAS,
            "config": {
                "syncMode":        "INHERIT",
                "attribute":       "Role",          # SAML assertion attribute name
                "attribute.value": saml_attribute_value,
                "role":            keycloak_role,
            },
        }
        _upsert_mapper(admin, mapper)
        print(f"  SAML mapper '{mapper_name}' configured ({saml_attribute_value} → {keycloak_role})")


def print_sp_metadata_endpoint() -> None:
    """
    Print the SP metadata URL that the on-premises IdP administrator
    uses to register ContextIQ as a trusted SAML Service Provider.
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
```

---

### SP metadata template (documentation aid — not generated by this script)

```xml
<!-- scripts/keycloak/saml_idp_metadata.xml.template -->
<!--
  This template documents the SAML SP metadata fields that Keycloak exposes at:
    GET /auth/realms/contextiq/protocol/saml/descriptor

  Share the live URL with your on-premises IdP administrator.
  Do NOT hard-code this file — always fetch live metadata from the Keycloak endpoint.

  Key fields your IdP admin needs:
    - EntityDescriptor[@entityID]    → ContextIQ SAML SP entity ID
    - AssertionConsumerService[@Location] → ACS URL (POST binding)
    - KeyDescriptor[@use="signing"]  → SP signing certificate (for signed AuthnRequests)
-->
<EntityDescriptor entityID="https://contextiq.internal/auth/realms/contextiq"
                  xmlns="urn:oasis:names:tc:SAML:2.0:metadata">
  <SPSSODescriptor
      AuthnRequestsSigned="true"
      WantAssertionsSigned="true"
      protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <AssertionConsumerService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        Location="https://contextiq.internal/auth/realms/contextiq/broker/saml-onprem/endpoint"
        index="1"/>
  </SPSSODescriptor>
</EntityDescriptor>
```

## Acceptance Criteria

- [ ] `configure_saml_broker.py` runs idempotently — re-running produces no duplicates (AC-7)
- [ ] Keycloak Admin Console shows the `saml-onprem` identity provider in the `contextiq` realm (AC-7)
- [ ] `GET /auth/realms/contextiq/protocol/saml/descriptor` returns valid SAML SP XML metadata (AC-7)
- [ ] A test user authenticated via a mock SAML assertion with `Role=ContextIQ-Auditors` receives the `auditor` Keycloak realm role (AC-7)
- [ ] `saml-idp-secret.yaml` contains only `PLACEHOLDER` values — no real certificates (OWASP A02)
- [ ] `syncMode: FORCE` ensures role mappings are re-evaluated on every SAML login (AC-7)

## Dependencies

- TASK-US043-01 — `contextiq` realm with PlatformRole realm roles and `saml-idp-certificate` Secret
- `scripts/keycloak/idp_config.yaml` from TASK-US043-02 — shared group-to-role mapping table
- Vault path `contextiq/data/keycloak/saml_idp` populated with on-prem IdP metadata

## Definition of Done

- [ ] `python scripts/keycloak/configure_saml_broker.py` completes without error against staging Keycloak
- [ ] `mypy --strict scripts/keycloak/configure_saml_broker.py` passes
- [ ] Manual test: mock SAML assertion (e.g. with `saml2-mock`) produces a Keycloak JWT with correct role
