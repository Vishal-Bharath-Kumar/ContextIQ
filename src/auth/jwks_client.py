"""
Async JWKS client for Keycloak RS256 token verification — TASK-US043-03.

Keys are cached for `_JWKS_TTL_SECONDS` (5 min) matching Keycloak's JWKS
rotation cadence.  On a kid-miss (rotated key), a single forced refresh is
attempted before raising JWTError.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from jose import jwt as jose_jwt
from jose.exceptions import JWTError

from src.auth.keycloak_settings import KeycloakSettings

logger = logging.getLogger(__name__)

# Cache TTL aligned with Keycloak JWKS rotation frequency (AC-6)
_JWKS_TTL_SECONDS: int = 300


def _find_jwk(jwks_data: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    """Return the first JWK whose `kid` matches, or None."""
    return next(
        (k for k in jwks_data.get("keys", []) if k.get("kid") == kid),
        None,
    )


class JWKSClient:
    """
    Fetches and caches Keycloak's public signing keys.

    - Keys are cached for `_JWKS_TTL_SECONDS` seconds (5 min).
    - On cache miss or expiry the JWKS endpoint is fetched from Keycloak.
    - Cache reads and writes are protected by `asyncio.Lock`.
    - Key rotation: on kid-miss a single forced refresh is attempted.

    Usage::

        client = JWKSClient(settings)
        await client.startup()              # pre-warm on app start
        claims = await client.decode(token) # raises JWTError on failure
        await client.shutdown()             # close httpx transport
    """

    def __init__(self, settings: KeycloakSettings | None = None) -> None:
        self._settings: KeycloakSettings = settings or KeycloakSettings()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._jwks_cache: dict[str, Any] | None = None
        self._cached_at: float = 0.0
        self._http: httpx.AsyncClient | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Open the HTTP transport and pre-warm the JWKS cache."""
        self._http = httpx.AsyncClient(timeout=10.0, verify=True)
        await self._refresh_keys()

    async def shutdown(self) -> None:
        """Release the underlying httpx transport."""
        if self._http is not None:
            await self._http.aclose()

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _refresh_keys(self) -> None:
        """Fetch JWKS from Keycloak and update the cache (caller holds the lock)."""
        assert self._http is not None, "JWKSClient.startup() must be called first"
        url = self._settings.jwks_uri
        logger.debug("Fetching JWKS from %s", url)
        response = await self._http.get(url)
        response.raise_for_status()
        self._jwks_cache = response.json()
        self._cached_at = time.monotonic()

    async def _get_keys(self) -> dict[str, Any]:
        """Return the cached JWKS document, refreshing if stale."""
        async with self._lock:
            age = time.monotonic() - self._cached_at
            if self._jwks_cache is None or age > _JWKS_TTL_SECONDS:
                await self._refresh_keys()
            # BUG FIX: assert non-None (guaranteed by _refresh_keys above)
            # and return inside the lock to prevent a race between lock release
            # and the return statement.
            assert self._jwks_cache is not None
            return self._jwks_cache

    async def _invalidate_and_refresh(self) -> dict[str, Any]:
        """
        Force a cache refresh — called when a kid is not found (key rotation).

        BUG FIX (spec): the force-refresh must also hold the lock so that
        concurrent decode() calls for the same rotated kid don't all trigger
        independent Keycloak fetches.
        """
        async with self._lock:
            self._cached_at = 0.0  # force expiry so next _get_keys refreshes
            await self._refresh_keys()
            assert self._jwks_cache is not None
            return self._jwks_cache

    # ── Public API ────────────────────────────────────────────────────────────

    async def decode(self, token: str) -> dict[str, Any]:
        """
        Verify and decode a Keycloak JWT.

        Validates:
          - Signature against cached RS256 public key
          - `iss` (issuer) claim against `KeycloakSettings.issuer`
          - `aud` (audience) claim against `KeycloakSettings.audience`
          - `exp` claim — enforces 5-min access token lifetime (AC-6)
          - `iat` and `nbf` claims

        On kid-miss, attempts a single forced JWKS refresh (key rotation).
        Raises `jose.exceptions.JWTError` on any validation failure.
        """
        settings = self._settings

        try:
            header: dict[str, Any] = jose_jwt.get_unverified_header(token)
        except JWTError as exc:
            raise JWTError(f"Malformed JWT header: {exc}") from exc

        kid: str | None = header.get("kid")

        # Try cached keys first
        jwks_data = await self._get_keys()
        matching_key = _find_jwk(jwks_data, kid)

        if matching_key is None:
            # kid not found — keys may have rotated; force one refresh and retry
            logger.info("kid=%r not in JWKS cache — forcing refresh", kid)
            jwks_data = await self._invalidate_and_refresh()
            matching_key = _find_jwk(jwks_data, kid)

        if matching_key is None:
            raise JWTError(
                f"No matching key for kid={kid!r} in Keycloak JWKS after refresh"
            )

        claims: dict[str, Any] = jose_jwt.decode(
            token,
            matching_key,   # pass the raw JWK dict — python-jose constructs the key
            algorithms=settings.algorithms,
            audience=settings.audience,
            issuer=settings.issuer,
            options={
                "verify_exp": True,   # AC-6: enforce 5-min access token lifetime
                "verify_iat": True,
                "verify_nbf": True,
            },
        )
        return claims
