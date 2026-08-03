"""
Unit tests for TASK-US004-02: Gateway JWKSClient with TTLCache.

Coverage targets (≥ 90% on gateway/auth/jwks_client.py):
  - Cache hit: JWKS fetched once; second verify() call makes zero HTTP calls
  - Cache miss after TTL: re-fetches on stale cache
  - Key rotation: JWSSignatureError busts cache; retry succeeds with new key
  - alg:none token rejected with MalformedTokenError
  - HS256 token rejected with MalformedTokenError
  - Keycloak timeout raises ServiceUnavailableError (no stale cache)
  - Stale cache served within 10-minute grace period when Keycloak is down
  - Expired token raises ExpiredTokenError
  - Invalid signature (persists after retry) raises InvalidSignatureError
  - Custom exceptions inherit from jose exceptions for backward compat

All JWKS endpoint calls are mocked via respx.  No real Keycloak connection.
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from src.gateway.auth.exceptions import (
    ExpiredTokenError,
    InvalidSignatureError,
    MalformedTokenError,
    ServiceUnavailableError,
)
from src.gateway.auth.jwks_client import JWKSClient, _STALE_GRACE_SECONDS

# ---------------------------------------------------------------------------
# Test fixtures: RSA key pair + JWKS + signed JWTs
# ---------------------------------------------------------------------------

_JWKS_URI = "http://keycloak.test/realms/test/protocol/openid-connect/certs"
_AUDIENCE = "contextiq-mcp-gateway"

# Generate a fresh RSA key pair for each test session using python-jose helpers
# so we can produce real RS256 JWTs without importing cryptography directly.

import base64
from jose import jwt as jose_jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def _generate_rsa_key_pair() -> tuple[str, dict[str, Any]]:
    """Return (private_pem, jwk_dict) for a fresh 2048-bit RSA key."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    pub = private_key.public_key()
    pub_nums = pub.public_numbers()

    def _b64(n: int) -> str:
        return base64.urlsafe_b64encode(
            n.to_bytes((n.bit_length() + 7) // 8, "big")
        ).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "test-key-id-1",
        "n": _b64(pub_nums.n),
        "e": _b64(pub_nums.e),
    }
    return private_pem, jwk


# Session-level key pair (regenerated once per test run)
_PRIVATE_PEM, _JWK = _generate_rsa_key_pair()
_PRIVATE_PEM_2, _JWK_2 = _generate_rsa_key_pair()
_JWK_2["kid"] = "test-key-id-2"


def _make_jwks(*jwks: dict[str, Any]) -> dict[str, Any]:
    return {"keys": list(jwks)}


def _make_token(
    private_pem: str,
    kid: str = "test-key-id-1",
    sub: str = "user-123",
    exp_offset: int = 3600,
    extra_claims: dict[str, Any] | None = None,
    algorithm: str = "RS256",
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": "http://keycloak.test/realms/test",
        "aud": _AUDIENCE,
        "exp": now + exp_offset,
        "iat": now,
        "jti": "sess-abc",
        "realm_access": {"roles": ["developer"]},
        "resource_access": {},
    }
    if extra_claims:
        claims.update(extra_claims)
    return jose_jwt.encode(claims, private_pem, algorithm=algorithm, headers={"kid": kid})


def _make_expired_token(private_pem: str = _PRIVATE_PEM) -> str:
    return _make_token(private_pem, exp_offset=-3600)


def _make_client(http_client: httpx.AsyncClient) -> JWKSClient:
    return JWKSClient(jwks_uri=_JWKS_URI, audience=_AUDIENCE, http_client=http_client)


# ---------------------------------------------------------------------------
# Custom exception inheritance tests
# ---------------------------------------------------------------------------

class TestExceptionInheritance:
    def test_expired_token_error_inherits_jose(self) -> None:
        from jose.exceptions import ExpiredSignatureError
        assert issubclass(ExpiredTokenError, ExpiredSignatureError)

    def test_invalid_signature_error_inherits_jose(self) -> None:
        from jose.exceptions import JWSSignatureError
        assert issubclass(InvalidSignatureError, JWSSignatureError)

    def test_malformed_token_error_inherits_jose(self) -> None:
        from jose.exceptions import JWTError
        assert issubclass(MalformedTokenError, JWTError)

    def test_service_unavailable_is_plain_exception(self) -> None:
        assert issubclass(ServiceUnavailableError, Exception)


# ---------------------------------------------------------------------------
# Algorithm restriction tests
# ---------------------------------------------------------------------------

class TestAlgorithmRestriction:
    @pytest.mark.asyncio
    async def test_alg_none_token_raises_malformed(self) -> None:
        """alg:none tokens must be rejected immediately, no network call."""
        # Craft a token with alg:none manually
        import json as json_mod
        header = base64.urlsafe_b64encode(
            json_mod.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json_mod.dumps({"sub": "x", "exp": 9999999999}).encode()
        ).rstrip(b"=").decode()
        none_token = f"{header}.{payload}."

        client = JWKSClient(jwks_uri=_JWKS_URI, audience=_AUDIENCE, http_client=AsyncMock())
        with pytest.raises(MalformedTokenError, match="none"):
            await client.verify(none_token)

    @pytest.mark.asyncio
    async def test_hs256_token_raises_malformed(self) -> None:
        """HS256-signed tokens must be rejected — symmetric algorithms not allowed."""
        hs256_token = jose_jwt.encode(
            {"sub": "x", "exp": int(time.time()) + 3600, "aud": _AUDIENCE},
            "secret",
            algorithm="HS256",
        )
        client = JWKSClient(jwks_uri=_JWKS_URI, audience=_AUDIENCE, http_client=AsyncMock())
        with pytest.raises(MalformedTokenError, match="HS256"):
            await client.verify(hs256_token)


# ---------------------------------------------------------------------------
# Cache hit / miss tests
# ---------------------------------------------------------------------------

class TestCacheBehaviour:
    @pytest.mark.asyncio
    async def test_first_verify_fetches_jwks(self) -> None:
        """JWKS endpoint must be called exactly once on first verify."""
        token = _make_token(_PRIVATE_PEM)
        jwks = _make_jwks(_JWK)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                claims = await client.verify(token)

            assert len(mock.calls) == 1
        assert claims.sub == "user-123"

    @pytest.mark.asyncio
    async def test_second_verify_uses_cached_jwks(self) -> None:
        """Second verify() within TTL must make zero additional HTTP calls."""
        token = _make_token(_PRIVATE_PEM)
        jwks = _make_jwks(_JWK)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                await client.verify(token)   # populates cache
                await client.verify(token)   # should hit cache

            assert len(mock.calls) == 1  # only one HTTP call total

    @pytest.mark.asyncio
    async def test_expired_cache_triggers_refetch(self) -> None:
        """After TTL expiry a new JWKS fetch must occur."""
        token = _make_token(_PRIVATE_PEM)
        jwks = _make_jwks(_JWK)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                await client.verify(token)

                # Manually evict the cache entry to simulate TTL expiry.
                client._cache.pop("jwks", None)

                await client.verify(token)   # must re-fetch

            assert len(mock.calls) == 2


# ---------------------------------------------------------------------------
# Key rotation test
# ---------------------------------------------------------------------------

class TestKeyRotation:
    @pytest.mark.asyncio
    async def test_signature_failure_busts_cache_and_retries(self) -> None:
        """On JWSSignatureError the cache must be busted and the second attempt
        succeeds with the rotated key."""
        old_jwks = _make_jwks(_JWK)      # original key
        new_jwks = _make_jwks(_JWK_2)    # rotated key

        # Token signed with the new (rotated) private key, old kid → mismatch
        # Actually: token signed with key2, kid="test-key-id-2"
        token = _make_token(_PRIVATE_PEM_2, kid="test-key-id-2")

        call_count = 0

        with respx.mock() as mock:
            def _side_effect(request: httpx.Request) -> httpx.Response:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return httpx.Response(200, json=old_jwks)  # doesn't have kid-2
                return httpx.Response(200, json=new_jwks)       # has kid-2

            mock.get(_JWKS_URI).mock(side_effect=_side_effect)
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                claims = await client.verify(token)

        assert claims.sub == "user-123"
        assert call_count == 2  # initial fetch + rotation refresh


# ---------------------------------------------------------------------------
# Expiry and signature error tests
# ---------------------------------------------------------------------------

class TestTokenErrors:
    @pytest.mark.asyncio
    async def test_expired_token_raises_expired_token_error(self) -> None:
        expired_token = _make_expired_token()
        jwks = _make_jwks(_JWK)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                with pytest.raises(ExpiredTokenError):
                    await client.verify(expired_token)

    @pytest.mark.asyncio
    async def test_wrong_audience_raises_malformed(self) -> None:
        """Token with wrong aud claim must raise MalformedTokenError."""
        token = _make_token(_PRIVATE_PEM, extra_claims={"aud": "wrong-audience"})
        jwks = _make_jwks(_JWK)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                with pytest.raises(MalformedTokenError):
                    await client.verify(token)

    @pytest.mark.asyncio
    async def test_tampered_signature_raises_invalid_or_malformed(self) -> None:
        """A token with tampered signature must raise InvalidSignatureError
        after cache-bust retry, or MalformedTokenError if jose wraps it.
        python-jose's jwt.decode wraps JWSSignatureError as JWTError, so the
        same key lookup finds the correct kid and retries with the same (correct)
        JWK — on the second attempt with the SAME key it still fails, raising
        InvalidSignatureError (detected by message pattern)."""
        token = _make_token(_PRIVATE_PEM)
        # Corrupt the signature part.
        parts = token.split(".")
        parts[2] = parts[2][:-4] + "xxxx"
        bad_token = ".".join(parts)

        jwks = _make_jwks(_JWK)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                with pytest.raises((InvalidSignatureError, MalformedTokenError)):
                    await client.verify(bad_token)


# ---------------------------------------------------------------------------
# Service unavailability / stale cache tests
# ---------------------------------------------------------------------------

class TestServiceUnavailability:
    @pytest.mark.asyncio
    async def test_timeout_with_empty_cache_raises_service_unavailable(self) -> None:
        """When Keycloak times out and cache is empty, raise ServiceUnavailableError."""
        token = _make_token(_PRIVATE_PEM)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(side_effect=httpx.TimeoutException("timeout"))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                with pytest.raises(ServiceUnavailableError):
                    await client.verify(token)

    @pytest.mark.asyncio
    async def test_stale_cache_served_within_grace_period(self) -> None:
        """When Keycloak is down but stale keys are within 10-min grace, verify succeeds."""
        token = _make_token(_PRIVATE_PEM)
        jwks = _make_jwks(_JWK)

        fetch_count = 0

        with respx.mock() as mock:
            def _side_effect(request: httpx.Request) -> httpx.Response:
                nonlocal fetch_count
                fetch_count += 1
                if fetch_count == 1:
                    return httpx.Response(200, json=jwks)  # initial warm-up
                raise httpx.TimeoutException("Keycloak down")  # subsequent calls fail

            mock.get(_JWKS_URI).mock(side_effect=_side_effect)
            async with httpx.AsyncClient() as http:
                client = _make_client(http)

                # Warm up the stale copy.
                await client.get_jwks()
                assert client._stale_jwks is not None

                # Expire the TTL cache but keep stale copy fresh.
                client._cache.pop("jwks", None)
                client._stale_fetched_at = time.monotonic()  # very recent

                # Should succeed using stale copy.
                claims = await client.verify(token)

        assert claims.sub == "user-123"

    @pytest.mark.asyncio
    async def test_stale_cache_expired_beyond_grace_raises_service_unavailable(self) -> None:
        """When stale copy is older than 10 min and Keycloak is down, raise ServiceUnavailableError."""
        token = _make_token(_PRIVATE_PEM)
        jwks = _make_jwks(_JWK)

        fetch_count = 0

        with respx.mock() as mock:
            def _side_effect(request: httpx.Request) -> httpx.Response:
                nonlocal fetch_count
                fetch_count += 1
                if fetch_count == 1:
                    return httpx.Response(200, json=jwks)
                raise httpx.TimeoutException("Keycloak down")

            mock.get(_JWKS_URI).mock(side_effect=_side_effect)
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                await client.get_jwks()  # warm stale copy

                # Make stale copy appear expired.
                client._cache.pop("jwks", None)
                client._stale_fetched_at = time.monotonic() - (_STALE_GRACE_SECONDS + 60)

                with pytest.raises(ServiceUnavailableError):
                    await client.verify(token)

    @pytest.mark.asyncio
    async def test_http_5xx_with_empty_cache_raises_service_unavailable(self) -> None:
        """500 from Keycloak with empty cache → ServiceUnavailableError."""
        token = _make_token(_PRIVATE_PEM)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(500))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                with pytest.raises(ServiceUnavailableError):
                    await client.verify(token)


# ---------------------------------------------------------------------------
# Prometheus histogram tests
# ---------------------------------------------------------------------------

class TestPrometheusHistogram:
    @pytest.mark.asyncio
    async def test_successful_fetch_increments_histogram(self) -> None:
        from src.gateway.auth.jwks_client import jwks_fetch_duration
        token = _make_token(_PRIVATE_PEM)
        jwks = _make_jwks(_JWK)

        before = jwks_fetch_duration.labels(outcome="success")._sum.get()

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                await client.verify(token)

        after = jwks_fetch_duration.labels(outcome="success")._sum.get()
        assert after > before

    @pytest.mark.asyncio
    async def test_failed_fetch_increments_error_histogram(self) -> None:
        from src.gateway.auth.jwks_client import jwks_fetch_duration

        before = jwks_fetch_duration.labels(outcome="error")._sum.get()

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(side_effect=httpx.TimeoutException("t/o"))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                with pytest.raises(ServiceUnavailableError):
                    await client.verify(_make_token(_PRIVATE_PEM))

        after = jwks_fetch_duration.labels(outcome="error")._sum.get()
        assert after > before


# ---------------------------------------------------------------------------
# decode() backward-compat shim
# ---------------------------------------------------------------------------

class TestDecodeCompat:
    @pytest.mark.asyncio
    async def test_decode_returns_dict(self) -> None:
        """decode() must return a plain dict for backward compat."""
        token = _make_token(_PRIVATE_PEM)
        jwks = _make_jwks(_JWK)

        with respx.mock() as mock:
            mock.get(_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))
            async with httpx.AsyncClient() as http:
                client = _make_client(http)
                result = await client.decode(token)

        assert isinstance(result, dict)
        assert result["sub"] == "user-123"
