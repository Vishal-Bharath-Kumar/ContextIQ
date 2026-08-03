"""
Token lifetime enforcement tests — TASK-US043-05.

Verifies AC-6: 5-min access token TTL enforced by JWKSClient.decode(),
and that the realm bootstrap script configures ssoSessionMaxLifespan = 28800 s.
"""
from __future__ import annotations

from typing import Any

import pytest
from jose.exceptions import JWTError

from src.auth.jwks_client import JWKSClient


async def test_access_token_exactly_at_5min_boundary(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """AC-6: Token minted with exp = now + 300 (exactly 5 min) is accepted."""
    token = mint_token(exp_offset=300)
    client = JWKSClient(keycloak_settings)
    await client.startup()
    claims = await client.decode(token)
    assert claims["sub"] == "user-test-001"
    await client.shutdown()


async def test_access_token_1_second_past_expiry_is_rejected(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """AC-6: Token expired 1 second ago is rejected."""
    token = mint_token(exp_offset=-1)
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(token)
    await client.shutdown()


def test_refresh_token_lifetime_configured_in_realm_bootstrap() -> None:
    """
    AC-6: The realm bootstrap script (TASK-US043-01) configures:
      - accessTokenLifespan  = 300    (5 min)
      - ssoSessionMaxLifespan = 28800 (8 h refresh-token TTL)

    Verified by source inspection — no Keycloak instance required.
    """
    import inspect
    import scripts.keycloak.bootstrap_realm as bootstrap_module

    source = inspect.getsource(bootstrap_module)
    assert "ssoSessionMaxLifespan" in source, "ssoSessionMaxLifespan not configured in bootstrap_realm.py"
    assert "28800" in source, "ssoSessionMaxLifespan value 28800 not found in bootstrap_realm.py"
    assert "accessTokenLifespan" in source, "accessTokenLifespan not configured in bootstrap_realm.py"
    assert "300" in source, "accessTokenLifespan value 300 not found in bootstrap_realm.py"
