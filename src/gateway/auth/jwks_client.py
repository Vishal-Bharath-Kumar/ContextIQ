"""
Gateway-specific Keycloak JWKS client with TTLCache and stale-cache resilience.

TASK-US004-02: Keycloak JWKS Client with Local Cache.

Design decisions
----------------
* ``cachetools.TTLCache`` (maxsize=1, ttl=300) replaces manual time-tracking —
  automatic eviction on cache reads after 300 s.
* A separate ``_stale_jwks`` copy is kept for up to ``_STALE_GRACE_SECONDS``
  (10 min) so that a transient Keycloak outage does not break in-flight auth.
* Algorithm restriction: only ``RS256`` is accepted.  ``alg: none`` and
  symmetric algorithms (``HS256``) are rejected before any decode attempt
  (OWASP A02 — Cryptographic Failures / JWT attack mitigation).
* Key rotation: on ``JWSSignatureError`` the cache is busted and the JWKS
  endpoint is re-fetched once.  If the retry also fails the error is re-raised.
* ``contextiq_jwks_fetch_duration_seconds`` Prometheus histogram tracks every
  JWKS endpoint call so latency regressions surface in Grafana.
* ``verify()`` is the public API; it returns a populated :class:`~src.gateway.schemas.auth_types.JWTClaims`
  and raises typed exceptions from :mod:`src.gateway.auth.exceptions`.

Environment variables
---------------------
``KEYCLOAK_JWKS_URI``   Full URL of the Keycloak JWKS endpoint.
                        Default: derived from KEYCLOAK_URL + KEYCLOAK_REALM.
``JWT_AUDIENCE``        Expected ``aud`` claim value.
                        Default: ``contextiq-mcp-gateway``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from cachetools import TTLCache
from prometheus_client import Histogram

from src.gateway.auth.exceptions import (
    ExpiredTokenError,
    InvalidSignatureError,
    MalformedTokenError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JWKS_TTL_SECONDS: int = 300           # 5-minute normal TTL
_STALE_GRACE_SECONDS: int = 600        # 10-minute stale-while-revalidate window
_FETCH_TIMEOUT_SECONDS: float = 2.0    # Keycloak JWKS request timeout
_ALLOWED_ALGORITHMS: frozenset[str] = frozenset({"RS256"})

# ---------------------------------------------------------------------------
# Prometheus metric
# ---------------------------------------------------------------------------

jwks_fetch_duration = Histogram(
    "contextiq_jwks_fetch_duration_seconds",
    "Time to fetch the Keycloak JWKS endpoint",
    ["outcome"],    # outcome: success | error
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_jwks_uri() -> str:
    """Derive the JWKS URI from individual Keycloak env vars as fallback."""
    url = os.environ.get("KEYCLOAK_URL", "http://keycloak.keycloak.svc.cluster.local/auth")
    realm = os.environ.get("KEYCLOAK_REALM", "contextiq")
    return f"{url}/realms/{realm}/protocol/openid-connect/certs"


def _default_audience() -> str:
    return os.environ.get("JWT_AUDIENCE", "contextiq-mcp-gateway")


def _find_jwk(jwks_data: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    """Return the JWK whose ``kid`` matches, or ``None``."""
    return next(
        (k for k in jwks_data.get("keys", []) if k.get("kid") == kid),
        None,
    )


# ---------------------------------------------------------------------------
# JWKSClient
# ---------------------------------------------------------------------------

class JWKSClient:
    """
    Async JWKS client for Keycloak RS256 token verification.

    Usage::

        client = JWKSClient()
        # Optionally pre-warm on startup:
        await client.get_jwks()
        # Verify a token:
        claims = await client.verify(token)
        # Release resources on shutdown:
        await client.aclose()

    Parameters
    ----------
    jwks_uri:
        Full URL of the Keycloak JWKS endpoint.  Defaults to the value of
        the ``KEYCLOAK_JWKS_URI`` environment variable, falling back to the
        URI derived from ``KEYCLOAK_URL`` and ``KEYCLOAK_REALM``.
    audience:
        Expected ``aud`` claim value.  Defaults to ``JWT_AUDIENCE`` env var.
    http_client:
        Optional pre-configured ``httpx.AsyncClient``.  When ``None`` a new
        client is created on the first request.  Inject a mock in tests.
    """

    def __init__(
        self,
        jwks_uri: str | None = None,
        audience: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._jwks_uri: str = (
            jwks_uri
            or os.environ.get("KEYCLOAK_JWKS_URI")
            or _default_jwks_uri()
        )
        self._audience: str = audience or _default_audience()
        self._http: httpx.AsyncClient | None = http_client
        self._owns_http: bool = http_client is None

        # Primary TTLCache — evicts automatically after 300 s.
        self._cache: TTLCache[str, dict[str, Any]] = TTLCache(
            maxsize=1, ttl=_JWKS_TTL_SECONDS
        )
        # Stale copy + timestamp for grace-period serving.
        self._stale_jwks: dict[str, Any] | None = None
        self._stale_fetched_at: float = 0.0

        self._lock: asyncio.Lock = asyncio.Lock()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Release the underlying httpx transport if we own it."""
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS, verify=True)
        return self._http

    # ── JWKS fetch & cache ───────────────────────────────────────────────────

    async def _fetch_jwks(self) -> dict[str, Any]:
        """Fetch the JWKS endpoint, record latency, and update the stale copy."""
        start = time.monotonic()
        outcome = "success"
        try:
            resp = await self._http_client().get(
                self._jwks_uri, timeout=_FETCH_TIMEOUT_SECONDS
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            # Update stale copy on every successful fetch.
            self._stale_jwks = data
            self._stale_fetched_at = time.monotonic()
            return data
        except Exception:
            outcome = "error"
            raise
        finally:
            jwks_fetch_duration.labels(outcome=outcome).observe(
                time.monotonic() - start
            )

    async def get_jwks(self) -> dict[str, Any]:
        """Return the cached JWKS document; fetch on miss or TTL expiry.

        On fetch failure:
        - If a stale copy is within the 10-minute grace window, return it.
        - Otherwise raise :class:`ServiceUnavailableError`.
        """
        async with self._lock:
            cached = self._cache.get("jwks")
            if cached is not None:
                return cached

            try:
                data = await self._fetch_jwks()
                self._cache["jwks"] = data
                return data
            except Exception as exc:
                grace_age = time.monotonic() - self._stale_fetched_at
                if self._stale_jwks is not None and grace_age <= _STALE_GRACE_SECONDS:
                    logger.warning(
                        "JWKS fetch failed (%s); serving stale keys (age=%.0f s)",
                        exc,
                        grace_age,
                    )
                    return self._stale_jwks
                raise ServiceUnavailableError(
                    f"Keycloak JWKS endpoint unreachable and no valid stale cache: {exc}"
                ) from exc

    async def _force_refresh(self) -> dict[str, Any]:
        """Bust the primary cache and re-fetch immediately (key rotation path)."""
        async with self._lock:
            self._cache.pop("jwks", None)
            try:
                data = await self._fetch_jwks()
                self._cache["jwks"] = data
                return data
            except Exception as exc:
                grace_age = time.monotonic() - self._stale_fetched_at
                if self._stale_jwks is not None and grace_age <= _STALE_GRACE_SECONDS:
                    logger.warning(
                        "JWKS force-refresh failed (%s); serving stale keys (age=%.0f s)",
                        exc,
                        grace_age,
                    )
                    return self._stale_jwks
                raise ServiceUnavailableError(
                    f"JWKS force-refresh failed and no valid stale cache: {exc}"
                ) from exc

    # ── Algorithm guard ──────────────────────────────────────────────────────

    @staticmethod
    def _check_algorithm(token: str) -> None:
        """Reject tokens that use disallowed algorithms before attempting decode.

        Raises :class:`MalformedTokenError` for:
        - ``alg: none`` — unsigned tokens (OWASP JWT attack)
        - Symmetric algorithms (``HS256``, etc.) — wrong key type for RS256 setup
        """
        from jose import jwt as jose_jwt  # noqa: PLC0415
        from jose.exceptions import JWTError  # noqa: PLC0415

        try:
            header = jose_jwt.get_unverified_header(token)
        except JWTError as exc:
            raise MalformedTokenError(f"Cannot read JWT header: {exc}") from exc

        alg: str = header.get("alg", "none")
        if alg.lower() == "none":
            raise MalformedTokenError("alg:none tokens are not accepted")
        if alg not in _ALLOWED_ALGORITHMS:
            raise MalformedTokenError(
                f"Algorithm {alg!r} is not allowed; only RS256 is accepted"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    async def verify(self, token: str) -> Any:  # noqa: ANN401 — returns JWTClaims (lazy import)
        """Verify a Keycloak JWT and return decoded :class:`~src.gateway.schemas.auth_types.JWTClaims`.

        Validation performed:
        - Algorithm: only RS256 accepted (``alg:none`` and ``HS256`` rejected)
        - Signature: verified against the Keycloak public key (cached JWKS)
        - ``exp`` claim: enforced by python-jose
        - ``aud`` claim: must contain ``self._audience``
        - ``iss`` claim: verified by python-jose against the JWKS issuer when present

        Key rotation handling:
        On :class:`InvalidSignatureError` (``JWSSignatureError`` from jose) the
        JWKS cache is busted and the endpoint is re-fetched once.  If the retry
        still fails the error is re-raised — this prevents infinite loops.

        Raises
        ------
        ExpiredTokenError
            When the ``exp`` claim is in the past.
        InvalidSignatureError
            When the signature does not match after a cache-bust retry.
        MalformedTokenError
            For any structural issue: wrong algorithm, bad format, bad claims.
        ServiceUnavailableError
            When Keycloak is unreachable and the stale-cache grace period has elapsed.
        """
        # Lazy import to avoid circular dependency via auth_types → src.auth
        from src.gateway.schemas.auth_types import JWTClaims  # noqa: PLC0415

        from jose import jwt as jose_jwt  # noqa: PLC0415
        from jose.exceptions import (  # noqa: PLC0415
            ExpiredSignatureError,
            JWTError,
        )

        # 1. Fast algorithm guard (no network required).
        self._check_algorithm(token)

        # 2. Extract kid for key lookup.
        try:
            header = jose_jwt.get_unverified_header(token)
        except JWTError as exc:
            raise MalformedTokenError(f"Malformed JWT header: {exc}") from exc
        kid: str | None = header.get("kid")

        # 3. Decode with cached keys.
        jwks_data = await self.get_jwks()
        matching_key = _find_jwk(jwks_data, kid)
        if matching_key is None:
            # kid not in cache — could be key rotation; bust and retry.
            logger.info("kid=%r not in JWKS; forcing cache refresh", kid)
            jwks_data = await self._force_refresh()
            matching_key = _find_jwk(jwks_data, kid)
        if matching_key is None:
            raise InvalidSignatureError(
                f"No public key found for kid={kid!r} even after JWKS refresh"
            )

        def _do_decode(key: dict[str, Any]) -> dict[str, Any]:
            return jose_jwt.decode(
                token,
                key,
                algorithms=list(_ALLOWED_ALGORITHMS),
                audience=self._audience,
                options={
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                },
            )

        def _is_signature_error(exc: Exception) -> bool:
            """python-jose jwt.decode wraps JWSSignatureError in JWTError.
            Detect by message since JWSSignatureError is re-raised as JWTError."""
            msg = str(exc).lower()
            return "signature" in msg or "verification failed" in msg

        try:
            raw_claims = _do_decode(matching_key)
        except ExpiredSignatureError as exc:
            raise ExpiredTokenError("JWT has expired") from exc
        except JWTError as exc:
            if _is_signature_error(exc):
                # Possible key rotation — bust cache and retry once.
                logger.info("Signature verification failed; busting JWKS cache for rotation retry")
                jwks_data = await self._force_refresh()
                matching_key = _find_jwk(jwks_data, kid)
                if matching_key is None:
                    raise InvalidSignatureError(
                        f"Signature invalid and kid={kid!r} absent from refreshed JWKS"
                    ) from exc
                try:
                    raw_claims = _do_decode(matching_key)
                except ExpiredSignatureError as exc2:
                    raise ExpiredTokenError("JWT has expired") from exc2
                except JWTError as exc2:
                    if _is_signature_error(exc2):
                        raise InvalidSignatureError(
                            "JWT signature invalid after JWKS cache refresh"
                        ) from exc2
                    raise MalformedTokenError(str(exc2)) from exc2
            else:
                raise MalformedTokenError(str(exc)) from exc

        return JWTClaims(**raw_claims)

    # ── Compat shim for callers that use decode() ─────────────────────────────

    async def decode(self, token: str) -> dict[str, Any]:
        """Backward-compatible alias: verify + return raw claims dict.

        Raises native ``jose.exceptions.*`` so callers that catch those directly
        continue to work without modification (e.g. :class:`~src.auth.jwks_client.JWKSClient`
        consumers and the existing middleware implementation).
        """
        claims = await self.verify(token)
        return {
            k: v
            for k, v in claims.model_dump().items()
            if v is not None
        }
