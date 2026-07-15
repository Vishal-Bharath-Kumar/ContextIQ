"""
Shared pytest fixtures for tests/auth/ — TASK-US043-05.

Provides:
  - RSA key pair + JWKS payload (session scope — generated once)
  - ``mint_token`` factory (function scope)
  - ``keycloak_settings`` pointing at a test Keycloak URL
  - ``mock_jwks`` — respx mock for the JWKS endpoint
  - ``bypass_jwt_middleware`` — autouse pass-through for tests that inject
    claims via ``app.dependency_overrides`` instead of real Bearer tokens.
    Tests marked with ``@pytest.mark.real_middleware`` are exempt so that
    middleware integration tests can exercise the actual dispatch path.
"""
from __future__ import annotations

import base64
import time
from collections.abc import Generator
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt
from starlette.requests import Request
from starlette.responses import Response

from src.auth.jwks_client import JWKSClient
from src.auth.keycloak_settings import KeycloakSettings

_TEST_KC_URL = "https://keycloak.test"
_REALM = "contextiq"


# ---------------------------------------------------------------------------
# JWT middleware bypass (autouse, skipped for @pytest.mark.real_middleware)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def bypass_jwt_middleware(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Replace JWTAuthMiddleware.dispatch with a no-op pass-through.

    RBAC matrix tests inject claims via ``app.dependency_overrides`` and send
    no real Bearer token — the middleware must be bypassed so it does not
    return 401 before the route executes.

    BUG FIX (spec): Tests marked with ``@pytest.mark.real_middleware`` are
    excluded so that middleware integration tests can test the actual dispatch
    path (401 for missing/expired tokens, etc.).
    """
    if request.node.get_closest_marker("real_middleware") is not None:
        return  # real middleware required — do not patch

    async def _passthrough(self: Any, request: Request, call_next: Any) -> Response:
        return await call_next(request)

    monkeypatch.setattr(
        "src.auth.middleware.JWTAuthMiddleware.dispatch",
        _passthrough,
    )


# ---------------------------------------------------------------------------
# RSA key pair — session scope (generated once per test session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def rsa_key_pair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    """Generate a 2048-bit RSA key pair for signing test tokens."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="session")
def kid() -> str:
    return "test-key-001"


@pytest.fixture(scope="session")
def jwks_payload(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey],
    kid: str,
) -> dict[str, Any]:
    """
    JWKS-format JSON payload matching the test RSA public key.

    BUG FIX (spec): removed dead-code ``hasattr(public_key, "public_key")``
    conditional — RSAPublicKey never has a ``public_key()`` method; the branch
    was always False.  Call ``public_key.public_numbers()`` directly.
    """
    _, public_key = rsa_key_pair
    pub_numbers = public_key.public_numbers()

    def _b64url_int(n: int) -> str:
        byte_length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n":   _b64url_int(pub_numbers.n),
                "e":   _b64url_int(pub_numbers.e),
            }
        ]
    }


# ---------------------------------------------------------------------------
# Token factory — function scope (fresh closure per test)
# ---------------------------------------------------------------------------

@pytest.fixture
def mint_token(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey],
    kid: str,
) -> Any:
    """
    Factory that mints RS256-signed JWTs with configurable claims.

    BUG FIX (spec): removed dead-code ``PublicFormat.SubjectPublicKeyInfo if False``
    conditional — the format is always ``PrivateFormat.TraditionalOpenSSL``.

    Usage::

        token = mint_token(roles=["admin"], exp_offset=300)
    """
    private_key, _ = rsa_key_pair
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    def _mint(
        roles: list[str] | None = None,
        exp_offset: int = 300,
        aud: str = "contextiq-mcp-gateway",
        iss: str = f"{_TEST_KC_URL}/realms/{_REALM}",
        sub: str = "user-test-001",
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub":                sub,
            "preferred_username": "testuser",
            "iss":                iss,
            "aud":                aud,
            "iat":                now,
            "exp":                now + exp_offset,
            "realm_access":       {"roles": roles or ["developer"]},
            "resource_access":    {},
        }
        return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})

    return _mint


# ---------------------------------------------------------------------------
# KeycloakSettings pointing at test URL
# ---------------------------------------------------------------------------

@pytest.fixture
def keycloak_settings() -> KeycloakSettings:
    return KeycloakSettings(
        url=_TEST_KC_URL,
        realm=_REALM,
        audience="contextiq-mcp-gateway",
        algorithms=["RS256"],
    )


# ---------------------------------------------------------------------------
# JWKS endpoint mock (respx)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_jwks(
    jwks_payload: dict[str, Any],
    keycloak_settings: KeycloakSettings,
) -> Generator[respx.MockRouter, None, None]:
    """
    Activate a respx mock for the Keycloak JWKS endpoint.

    BUG FIX (spec): removed ``base_url=jwks_uri`` from ``respx.mock()`` — when
    ``base_url`` equals the full JWKS URI, ``mock.get(jwks_uri)`` incorrectly
    doubles the path inside the base URL.  Route directly by full URI instead.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(keycloak_settings.jwks_uri).mock(
            return_value=httpx.Response(200, json=jwks_payload)
        )
        yield mock
