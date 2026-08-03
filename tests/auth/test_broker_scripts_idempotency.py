"""
Broker script idempotency tests — TASK-US043-05.

Verifies that both configure_entra_id_broker.py (AC-2) and
configure_saml_broker.py (AC-7) are idempotent: re-running creates no
duplicate identity providers or mappers.

Uses unittest.mock; no live Keycloak instance required.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def _make_mock_admin(
    existing_idps: list[str] | None = None,
    existing_mappers: list[str] | None = None,
) -> MagicMock:
    """
    Build a mock KeycloakAdmin pre-configured with existing aliases and mapper names.

    ``get_idps()``      → [{"alias": alias} for alias in existing_idps]
    ``get_idp_mappers`` → [{"name": name, "id": f"id-{name}"} for name in existing_mappers]

    The ``id`` field is required for the SAML broker's ``_upsert_mapper``
    (which calls ``update_mapper_in_idp(alias, existing["id"], payload)``).
    """
    admin = MagicMock()
    admin.get_idps.return_value = [{"alias": a} for a in (existing_idps or [])]
    admin.get_idp_mappers.return_value = [
        {"name": n, "id": f"id-{n}"} for n in (existing_mappers or [])
    ]
    return admin


# ---------------------------------------------------------------------------
# Entra ID OIDC broker idempotency (AC-2)
# ---------------------------------------------------------------------------


class TestEntraIdBrokerIdempotency:
    """Running configure_entra_id_broker.py twice produces no duplicate IdPs."""

    def test_create_called_when_idp_absent(self, monkeypatch: Any) -> None:
        from scripts.keycloak.configure_entra_id_broker import register_entra_id_broker

        admin = _make_mock_admin(existing_idps=[])
        monkeypatch.setenv("ENTRA_TENANT_ID", "test-tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "test-client")
        monkeypatch.setenv("ENTRA_CLIENT_SECRET", "test-secret")

        register_entra_id_broker(admin)

        admin.create_idp.assert_called_once()
        admin.update_idp.assert_not_called()

    def test_update_called_when_idp_exists(self, monkeypatch: Any) -> None:
        from scripts.keycloak.configure_entra_id_broker import register_entra_id_broker

        admin = _make_mock_admin(existing_idps=["entra-id"])
        monkeypatch.setenv("ENTRA_TENANT_ID", "test-tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "test-client")
        monkeypatch.setenv("ENTRA_CLIENT_SECRET", "test-secret")

        register_entra_id_broker(admin)

        admin.update_idp.assert_called_once()
        admin.create_idp.assert_not_called()

    def test_mapper_not_duplicated_if_already_exists(self, monkeypatch: Any) -> None:
        from scripts.keycloak.configure_entra_id_broker import configure_group_role_mappers

        # BUG FIX (spec): the spec only pre-populated `groups-to-{role}` names,
        # omitting `"claim-groups"`.  configure_group_role_mappers() creates the
        # claim extractor mapper BEFORE the role mappers; if it is absent from
        # the existing list, add_mapper_to_idp is called for it and
        # assert_not_called() fails.
        # Fix: include "claim-groups" in the existing mappers list.
        all_mapper_names = ["claim-groups"] + [
            f"groups-to-{r}"
            for r in [
                "admin",
                "platform_engineer",
                "security_officer",
                "developer",
                "manager",
                "auditor",
                "devops_sre",
            ]
        ]
        admin = _make_mock_admin(existing_mappers=all_mapper_names)

        configure_group_role_mappers(admin)

        admin.add_mapper_to_idp.assert_not_called()


# ---------------------------------------------------------------------------
# SAML broker idempotency (AC-7)
# ---------------------------------------------------------------------------


class TestSamlBrokerIdempotency:
    """Running configure_saml_broker.py twice produces no duplicate IdPs."""

    def test_create_called_when_idp_absent(self, monkeypatch: Any) -> None:
        from scripts.keycloak.configure_saml_broker import register_saml_broker

        admin = _make_mock_admin(existing_idps=[])
        monkeypatch.setenv("SAML_IDP_ENTITY_ID", "https://idp.example.com")
        monkeypatch.setenv("SAML_IDP_SSO_URL", "https://idp.example.com/sso")
        monkeypatch.setenv("SAML_IDP_SIGNING_CERT", "FAKECERT")

        register_saml_broker(admin)

        admin.create_idp.assert_called_once()
        admin.update_idp.assert_not_called()

    def test_update_called_when_idp_exists(self, monkeypatch: Any) -> None:
        from scripts.keycloak.configure_saml_broker import register_saml_broker

        admin = _make_mock_admin(existing_idps=["saml-onprem"])
        monkeypatch.setenv("SAML_IDP_ENTITY_ID", "https://idp.example.com")
        monkeypatch.setenv("SAML_IDP_SSO_URL", "https://idp.example.com/sso")
        monkeypatch.setenv("SAML_IDP_SIGNING_CERT", "FAKECERT")

        register_saml_broker(admin)

        admin.update_idp.assert_called_once()
        admin.create_idp.assert_not_called()
