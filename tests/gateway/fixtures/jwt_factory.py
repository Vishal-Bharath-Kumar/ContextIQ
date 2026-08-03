"""
JWT token factory for TASK-US004-05 security and performance tests.

Generates real RSA-signed JWTs and crafted attack tokens without connecting
to any live service.  All key material is ephemeral and scoped to the test
session.

Public API
----------
SESSION_PRIVATE_PEM : str        — PEM-encoded 2048-bit RSA private key (test signer)
SESSION_JWK         : dict       — Matching JWK (public key, kid="test-key-id-1")
SESSION_JWKS        : dict       — {"keys": [SESSION_JWK]} JWKS document

make_valid_token(sub, roles, exp_offset, kid) -> str
make_expired_token()                          -> str
make_nbf_future_token()                       -> str
make_none_alg_token()                         -> str
make_hs256_token(public_key_pem)              -> str   # algorithm confusion
make_tampered_token(sub_override)             -> str
make_missing_sub_token()                      -> str
make_wrong_key_token(roles)                   -> str   # signed with different RSA key
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

# ---------------------------------------------------------------------------
# Constants shared with tests
# ---------------------------------------------------------------------------

JWKS_URI = "http://keycloak.test/realms/test/protocol/openid-connect/certs"
AUDIENCE = "contextiq-mcp-gateway"
ISSUER = "http://keycloak.test/realms/test"
KID = "test-key-id-1"


# ---------------------------------------------------------------------------
# RSA key generation helpers
# ---------------------------------------------------------------------------

def _gen_rsa_pair(kid: str = KID) -> tuple[str, dict[str, Any]]:
    """Return (private_pem_str, jwk_dict) for a fresh 2048-bit RSA key."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem: str = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    pub_key = private_key.public_key()
    pub_nums = pub_key.public_numbers()

    def _b64url(n: int) -> str:
        return (
            base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big"))
            .rstrip(b"=")
            .decode()
        )

    pub_pem: str = pub_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    jwk: dict[str, Any] = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url(pub_nums.n),
        "e": _b64url(pub_nums.e),
        "_pub_pem": pub_pem,  # stored for algorithm-confusion test; ignored by real JWKS
    }
    return private_pem, jwk


# ---------------------------------------------------------------------------
# Session-level key material (generated once per test session)
# ---------------------------------------------------------------------------

SESSION_PRIVATE_PEM, SESSION_JWK = _gen_rsa_pair(kid=KID)
SESSION_JWKS: dict[str, Any] = {"keys": [SESSION_JWK]}

# A second distinct RSA key for role-escalation / wrong-key tests
_ALT_PRIVATE_PEM, _ALT_JWK = _gen_rsa_pair(kid="alt-key-id-2")
_ALT_JWKS: dict[str, Any] = {"keys": [_ALT_JWK]}


def get_alt_jwks() -> dict[str, Any]:
    """Return a JWKS containing only the *alternative* key (not in SESSION_JWKS)."""
    return _ALT_JWKS


def get_public_pem() -> str:
    """Return the PEM public key string for SESSION_JWK (used by algorithm-confusion test)."""
    return SESSION_JWK["_pub_pem"]


# ---------------------------------------------------------------------------
# Token factory functions
# ---------------------------------------------------------------------------

def _base_claims(
    sub: str = "user-001",
    roles: list[str] | None = None,
    exp_offset: int = 3600,
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + exp_offset,
        "iat": now,
        "jti": "sess-test-001",
        "email": "test@example.com",
        "preferred_username": sub,
        "realm_access": {"roles": roles or ["developer"]},
        "resource_access": {},
    }


def make_valid_token(
    sub: str = "user-001",
    roles: list[str] | None = None,
    exp_offset: int = 3600,
    kid: str = KID,
) -> str:
    """RS256 token signed with SESSION_PRIVATE_PEM; accepted by a client loaded with SESSION_JWKS."""
    claims = _base_claims(sub=sub, roles=roles, exp_offset=exp_offset)
    return jose_jwt.encode(claims, SESSION_PRIVATE_PEM, algorithm="RS256", headers={"kid": kid})


def make_expired_token() -> str:
    """Valid RS256 token whose ``exp`` is 1 second in the past."""
    claims = _base_claims(exp_offset=-1)
    return jose_jwt.encode(claims, SESSION_PRIVATE_PEM, algorithm="RS256", headers={"kid": KID})


def make_nbf_future_token() -> str:
    """Token with ``nbf`` set 1 hour in the future (not yet valid)."""
    claims = _base_claims()
    claims["nbf"] = int(time.time()) + 3600
    return jose_jwt.encode(claims, SESSION_PRIVATE_PEM, algorithm="RS256", headers={"kid": KID})


def make_none_alg_token() -> str:
    """Unsigned JWT with ``alg: none`` in the JOSE header (attack vector)."""
    header_b64 = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload_b64 = (
        base64.urlsafe_b64encode(
            json.dumps({
                "sub": "attacker",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            }).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    # No signature segment — "alg: none" tokens omit or leave it empty
    return f"{header_b64}.{payload_b64}."


def make_hs256_token(public_key_pem: str) -> str:
    """
    Algorithm-confusion attack: sign with the RS256 *public* key as if it were
    an HMAC-SHA256 secret.  A vulnerable library that accepts both HS256 and RS256
    would verify this using the public key as the HMAC secret.

    Modern python-jose (with cryptography backend) rejects RSA keys for HS256
    at encode time, so this token is constructed manually using raw HMAC-SHA256
    with the PEM bytes as the secret — exactly what a real attacker would do.
    """
    import hashlib
    import hmac as _hmac

    header = {"alg": "HS256", "typ": "JWT", "kid": KID}
    claims = _base_claims(sub="attacker-hs256")

    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    # Use the raw PEM bytes as the HMAC key (the classic algorithm-confusion attack)
    signature = _hmac.new(
        public_key_pem.encode(),
        signing_input,
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def make_tampered_token(sub_override: str = "admin-escalated") -> str:
    """
    Produce a token whose payload has been modified after signing so that
    the signature no longer matches the payload.

    Technique: encode a valid token, split the three parts, replace the
    base64url-encoded payload with a tampered one, re-join.  The header and
    signature remain from the original valid token.
    """
    original = make_valid_token(sub="legitimate-user")
    header_b64, _orig_payload_b64, sig_b64 = original.split(".")

    tampered_claims = _base_claims(sub=sub_override)
    tampered_payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(tampered_claims).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header_b64}.{tampered_payload_b64}.{sig_b64}"


def make_missing_sub_token() -> str:
    """Token that omits the ``sub`` claim (required by JWTClaims model)."""
    claims = _base_claims()
    del claims["sub"]
    return jose_jwt.encode(claims, SESSION_PRIVATE_PEM, algorithm="RS256", headers={"kid": KID})


def make_wrong_key_token(roles: list[str] | None = None) -> str:
    """
    Token signed with the *alternative* RSA key.  When the client only holds
    SESSION_JWKS the signature will not verify → invalid_signature.
    """
    claims = _base_claims(roles=roles or ["ADMIN"])
    return jose_jwt.encode(
        claims, _ALT_PRIVATE_PEM, algorithm="RS256", headers={"kid": _ALT_JWK["kid"]}
    )
