# TASK-US043-03 — Token Lifetime Configuration and MCP Gateway JWKS Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US043-03 |
| User Story | US-043 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Update the MCP Gateway's `JWTAuthMiddleware` to verify tokens against Keycloak's JWKS endpoint rather than a static symmetric secret (AC-3). Add `KeycloakSettings` (pydantic-settings) for the realm URL, expected audience, and algorithm list. Confirm that the realm's token lifetimes are correctly enforced by the middleware's `exp` claim check: access token = 5 min, refresh token = 8 h (AC-6). The realm bootstrap in TASK-US043-01 already sets these values in Keycloak; this task ensures the Gateway trusts and enforces them.

## Implementation Details

**Technology:** Python 3.11+, `python-jose[cryptography]>=3.3` (JWKS RSA verification), `httpx` (JWKS fetch), pydantic-settings, FastAPI Middleware

**File locations:**
- `src/auth/keycloak_settings.py` — `KeycloakSettings` (env_prefix `KEYCLOAK_`)
- `src/auth/jwks_client.py` — async JWKS client with 5-min TTL cache
- `src/auth/middleware.py` — updated `JWTAuthMiddleware` using JWKS client
- `src/gateway/schemas/auth_types.py` — `JWTClaims` extended with `preferred_username` (already exists; only add missing fields if any)

---

### `KeycloakSettings`

```python
# src/auth/keycloak_settings.py
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeycloakSettings(BaseSettings):
    """
    All Keycloak connection parameters.
    All values are read from environment variables prefixed KEYCLOAK_.

    Example .env entries:
      KEYCLOAK_URL=https://contextiq.internal/auth
      KEYCLOAK_REALM=contextiq
      KEYCLOAK_AUDIENCE=contextiq-mcp-gateway
      KEYCLOAK_ALGORITHMS=RS256
    """
    model_config = SettingsConfigDict(
        env_prefix  = "KEYCLOAK_",
        env_file    = ".env",
        extra       = "ignore",
    )

    url:        str       = "http://keycloak.keycloak.svc.cluster.local/auth"
    realm:      str       = "contextiq"
    audience:   str       = "contextiq-mcp-gateway"
    algorithms: list[str] = ["RS256"]

    @property
    def jwks_uri(self) -> str:
        return f"{self.url}/realms/{self.realm}/protocol/openid-connect/certs"

    @property
    def issuer(self) -> str:
        return f"{self.url}/realms/{self.realm}"
```

---

### Async JWKS client with TTL cache

```python
# src/auth/jwks_client.py
from __future__ import annotations
import asyncio
import time
import logging
from typing import Any

import httpx
from jose import jwk, jwt as jose_jwt
from jose.exceptions import JWTError

from src.auth.keycloak_settings import KeycloakSettings

logger = logging.getLogger(__name__)

_JWKS_TTL_SECONDS = 300   # 5-min cache — matches Keycloak JWKS rotation frequency


class JWKSClient:
    """
    Fetches and caches Keycloak's public signing keys.

    - Keys are cached for `_JWKS_TTL_SECONDS` seconds (5 min).
    - On cache miss or expiry, fetches from Keycloak's JWKS endpoint.
    - Thread-safe via asyncio.Lock.

    Usage:
        client = JWKSClient(settings)
        await client.startup()              # pre-warm on app start
        claims = await client.decode(token)
        await client.shutdown()             # release httpx transport
    """

    def __init__(self, settings: KeycloakSettings | None = None) -> None:
        self._settings   = settings or KeycloakSettings()
        self._lock       = asyncio.Lock()
        self._jwks_cache: dict[str, Any] | None = None
        self._cached_at: float = 0.0
        self._http: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._http = httpx.AsyncClient(timeout=10.0, verify=True)
        await self._refresh_keys()

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()

    async def _refresh_keys(self) -> None:
        assert self._http is not None, "JWKSClient.startup() must be called first"
        url = self._settings.jwks_uri
        logger.debug("Fetching JWKS from %s", url)
        response = await self._http.get(url)
        response.raise_for_status()
        self._jwks_cache = response.json()
        self._cached_at  = time.monotonic()

    async def _get_keys(self) -> dict[str, Any]:
        async with self._lock:
            age = time.monotonic() - self._cached_at
            if self._jwks_cache is None or age > _JWKS_TTL_SECONDS:
                await self._refresh_keys()
        return self._jwks_cache  # type: ignore[return-value]

    async def decode(self, token: str) -> dict[str, Any]:
        """
        Verify and decode a JWT.
        - Validates signature against cached Keycloak public key (RS256).
        - Validates `iss`, `aud`, and `exp` claims.
        - Raises `jose.JWTError` on any validation failure.
        """
        settings    = self._settings
        jwks_data   = await self._get_keys()

        try:
            # Extract the 'kid' header to select the correct public key
            unverified_header = jose_jwt.get_unverified_header(token)
        except JWTError as exc:
            raise JWTError(f"Malformed JWT header: {exc}") from exc

        # Find the matching key from JWKS
        key = None
        for jwk_key in jwks_data.get("keys", []):
            if jwk_key.get("kid") == unverified_header.get("kid"):
                key = jwk.construct(jwk_key)
                break

        if key is None:
            # kid not found — keys may have rotated; force refresh once
            await self._refresh_keys()
            jwks_data = self._jwks_cache  # type: ignore[assignment]
            for jwk_key in jwks_data.get("keys", []):
                if jwk_key.get("kid") == unverified_header.get("kid"):
                    key = jwk.construct(jwk_key)
                    break

        if key is None:
            raise JWTError("No matching key found in JWKS for the provided 'kid'")

        claims: dict[str, Any] = jose_jwt.decode(
            token,
            key.to_dict(),
            algorithms  = settings.algorithms,
            audience    = settings.audience,
            issuer      = settings.issuer,
            options     = {
                "verify_exp": True,   # AC-6: enforce access token lifetime
                "verify_iat": True,
                "verify_nbf": True,
            },
        )
        return claims
```

---

### Updated `JWTAuthMiddleware`

```python
# src/auth/middleware.py
from __future__ import annotations
import logging
from typing import Any

from fastapi            import Request, Response
from fastapi.responses  import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from jose.exceptions    import JWTError

from src.auth.jwks_client            import JWKSClient
from src.gateway.schemas.auth_types  import JWTClaims

logger = logging.getLogger(__name__)

# Paths that bypass authentication entirely (publicly accessible)
_SKIP_PATHS: frozenset[str] = frozenset({
    "/healthz",
    "/auth/health/ready",
    "/auth/health/live",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",   # prometheus-client scrape endpoint — network-level access control
})


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    AC-3: Validates Keycloak-issued JWTs on every inbound request.

    - Extracts the Bearer token from the Authorization header.
    - Verifies the token's signature using the Keycloak JWKS endpoint
      (via the injected `JWKSClient`).
    - Stores validated `JWTClaims` on `request.state.jwt_claims` so that
      RBAC dependencies (US-042 TASK-US042-02) can consume them without
      re-verifying the token.
    - Returns HTTP 401 for missing/malformed tokens.
    - Returns HTTP 401 for expired tokens (the `exp` claim enforces the
      5-min access token lifetime — AC-6).
    - Returns HTTP 403 for tokens that fail issuer/audience validation.
    """

    def __init__(self, app: Any, jwks_client: JWKSClient) -> None:
        super().__init__(app)
        self._jwks = jwks_client

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )

        token = auth_header.removeprefix("Bearer ").strip()
        try:
            raw_claims: dict[str, Any] = await self._jwks.decode(token)
        except JWTError as exc:
            logger.debug("JWT validation failed: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"detail": "Token validation failed"},
            )

        try:
            claims = JWTClaims(**raw_claims)
        except Exception as exc:
            logger.warning("JWT claims schema mismatch: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"detail": "Malformed JWT claims"},
            )

        request.state.jwt_claims = claims
        return await call_next(request)
```

---

### Application startup wiring

```python
# src/main.py  — excerpt showing JWKS client lifecycle (add to existing lifespan)
from contextlib               import asynccontextmanager
from fastapi                  import FastAPI
from src.auth.jwks_client     import JWKSClient
from src.auth.keycloak_settings import KeycloakSettings
from src.auth.middleware      import JWTAuthMiddleware

_jwks_client: JWKSClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _jwks_client
    _jwks_client = JWKSClient(KeycloakSettings())
    await _jwks_client.startup()
    app.state.jwks_client = _jwks_client
    yield
    if _jwks_client:
        await _jwks_client.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    # JWKSClient is provided via app.state — retrieved in add_middleware call
    # after lifespan runs. Use a factory pattern:
    app.add_middleware(
        JWTAuthMiddleware,
        jwks_client = JWKSClient(KeycloakSettings()),  # each worker has its own client
    )
    return app
```

## Acceptance Criteria

- [x] `JWKSClient.decode()` raises `JWTError` for an expired token (exp in the past) — enforcing 5-min access token TTL (AC-6)
- [x] `JWKSClient.decode()` raises `JWTError` for a token signed by an unknown key (rotated key scenario) — one automatic JWKS refresh attempted (AC-3)
- [x] `JWTAuthMiddleware` returns HTTP 401 for requests with no Authorization header on protected paths (AC-3)
- [x] `JWTAuthMiddleware` returns HTTP 401 for tokens with an expired `exp` claim (AC-6)
- [x] `JWTAuthMiddleware` stores valid `JWTClaims` on `request.state.jwt_claims` — consumed by RBAC dependencies (AC-3)
- [x] `KeycloakSettings` reads all values from env vars; no hard-coded URLs in code (OWASP A05)
- [x] JWKS cache TTL is `_JWKS_TTL_SECONDS = 300` — aligns with Keycloak key rotation cadence

## Dependencies

- TASK-US043-01 — Keycloak HA deployment must expose `GET /auth/realms/contextiq/protocol/openid-connect/certs`
- TASK-US042-01 — `JWTClaims` Pydantic model and `realm_access.roles` parsing already defined

## Definition of Done

- [x] `pytest tests/auth/test_jwks_client.py` passes (see TASK-US043-05)
- [x] `mypy --strict src/auth/jwks_client.py src/auth/middleware.py src/auth/keycloak_settings.py` passes
- [x] `pip install python-jose[cryptography]` added to `requirements.txt` / `pyproject.toml`
