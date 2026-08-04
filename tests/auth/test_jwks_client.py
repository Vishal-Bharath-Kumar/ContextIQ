"""
JWKS client unit tests — TASK-US043-05.

Verifies AC-3 (RS256 token validation), AC-6 (exp enforcement),
JWKS cache behaviour, and key-rotation refresh logic.
No live Keycloak required — uses respx + test RSA keys from conftest.
"""
from __future__ import annotations

import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from jose import jwt as jose_jwt
from jose.exceptions import JWTError

from src.auth.jwks_client import JWKSClient, _JWKS_TTL_SECONDS


# ---------------------------------------------------------------------------
# Basic decode
# ---------------------------------------------------------------------------


async def test_decode_valid_token(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """AC-3: Valid RS256-signed JWT is decoded and claims are returned."""
    token = mint_token(roles=["admin"])
    client = JWKSClient(keycloak_settings)
    await client.startup()
    claims = await client.decode(token)
    assert claims["realm_access"]["roles"] == ["admin"]
    await client.shutdown()


async def test_decode_expired_token_raises(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """AC-6: Expired token raises JWTError — enforces 5-min access token TTL."""
    token = mint_token(roles=["developer"], exp_offset=-1)  # already expired
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(token)
    await client.shutdown()


async def test_decode_wrong_audience_raises(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """Token for a different audience is rejected (AC-3 aud check)."""
    token = mint_token(aud="some-other-service")
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(token)
    await client.shutdown()


async def test_decode_keycloak_account_audience_with_matching_azp(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """Keycloak access tokens with aud=account are accepted when azp matches."""
    token = mint_token(aud="account", azp=keycloak_settings.client_id, roles=["admin"])
    client = JWKSClient(keycloak_settings)
    await client.startup()
    claims = await client.decode(token)
    assert claims["azp"] == keycloak_settings.client_id
    assert claims["aud"] == "account"
    await client.shutdown()


async def test_decode_keycloak_account_audience_with_wrong_azp_raises(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """Keycloak account-audience tokens are rejected when azp targets another client."""
    token = mint_token(aud="account", azp="some-other-client")
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(token)
    await client.shutdown()


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


async def test_jwks_cache_prevents_repeated_fetch(
    mock_jwks: Any,
    keycloak_settings: Any,
    mint_token: Any,
) -> None:
    """JWKS endpoint is fetched once at startup; 5 sequential decodes use the cache."""
    token = mint_token()
    client = JWKSClient(keycloak_settings)
    await client.startup()
    for _ in range(5):
        await client.decode(token)
    # startup() = 1 fetch; all decodes use the in-memory cache → ≤ 2 total
    assert mock_jwks.calls.call_count <= 2
    await client.shutdown()


# ---------------------------------------------------------------------------
# Key rotation: unknown kid triggers exactly one JWKS refresh
# ---------------------------------------------------------------------------


async def test_unknown_kid_triggers_refresh(
    mock_jwks: Any,
    keycloak_settings: Any,
    rsa_key_pair: Any,
) -> None:
    """
    AC-3: kid not in cached JWKS triggers one forced refresh, then raises JWTError
    (the refreshed mock still doesn't contain the unknown kid).

    Verifies call count: startup() → 1, _invalidate_and_refresh() → 1, total = 2.
    """
    private_key, _ = rsa_key_pair
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    now = int(time.time())
    unknown_kid_token: str = jose_jwt.encode(
        {
            "sub":                "u1",
            "preferred_username": "u1",
            "iss":                keycloak_settings.issuer,
            "aud":                keycloak_settings.audience,
            "iat":                now,
            "exp":                now + 300,
            "realm_access":       {"roles": ["developer"]},
            "resource_access":    {},
        },
        pem,
        algorithm="RS256",
        headers={"kid": "UNKNOWN-KEY-XYZ"},
    )

    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(unknown_kid_token)

    # startup() + one _invalidate_and_refresh() = exactly 2 fetches
    assert mock_jwks.calls.call_count == 2
    await client.shutdown()
