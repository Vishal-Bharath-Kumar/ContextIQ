# TASK-US004-02 — Keycloak JWKS Client with Local Cache

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US004-02 |
| User Story | US-004 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend / Security |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement the `JWKSClient` that fetches the Keycloak JSON Web Key Set, caches it locally with a 5-minute TTL, and verifies JWT signatures against the correct public key. This keeps token validation under 50 ms on cache hits and tolerates Keycloak transient unavailability.

## Implementation Details

**Technology:** Python 3.11+, `python-jose`, `httpx.AsyncClient`, `cachetools.TTLCache`

**File locations:**
- `src/gateway/auth/jwks_client.py` — `JWKSClient` class
- `src/gateway/auth/exceptions.py` — `ExpiredTokenError`, `InvalidSignatureError`, `MalformedTokenError`
- `tests/gateway/test_jwks_client.py`

**Keycloak JWKS endpoint:**
```
GET https://<keycloak-host>/realms/<realm>/protocol/openid-connect/certs
```
Configured via environment variable `KEYCLOAK_JWKS_URI`.

**`JWKSClient` design:**

```python
from cachetools import TTLCache
from jose import jwt, JWTError, ExpiredSignatureError

class JWKSClient:
    _cache: TTLCache[str, dict]  # key: "jwks", value: JWKS dict; TTL = 300 s

    def __init__(self, jwks_uri: str, http_client: httpx.AsyncClient):
        self.jwks_uri = jwks_uri
        self.http_client = http_client
        self._cache = TTLCache(maxsize=1, ttl=300)

    async def _fetch_jwks(self) -> dict:
        resp = await self.http_client.get(self.jwks_uri, timeout=2.0)
        resp.raise_for_status()
        return resp.json()

    async def get_jwks(self) -> dict:
        if "jwks" not in self._cache:
            self._cache["jwks"] = await self._fetch_jwks()
        return self._cache["jwks"]

    async def verify(self, token: str) -> JWTClaims:
        jwks = await self.get_jwks()
        try:
            claims = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                options={"verify_aud": False},  # audience verified separately
            )
            return JWTClaims.model_validate(claims)
        except ExpiredSignatureError:
            raise ExpiredTokenError()
        except JWTError as e:
            if "signature" in str(e).lower():
                raise InvalidSignatureError()
            raise MalformedTokenError(str(e))
```

**Key rotation handling:** If signature verification fails with a valid-looking token, invalidate the JWKS cache and retry once (handles key rotation without operator intervention):
```python
except InvalidSignatureError:
    # Possible key rotation — bust cache and retry
    self._cache.clear()
    jwks = await self._fetch_jwks()
    self._cache["jwks"] = jwks
    # Retry decode once; if still fails, re-raise
    try:
        claims = jwt.decode(token, jwks, algorithms=["RS256"], ...)
        return JWTClaims.model_validate(claims)
    except JWTError:
        raise InvalidSignatureError()
```

**Keycloak unavailability:** If JWKS fetch fails (timeout or 5xx) and cache is empty, raise `ServiceUnavailableError` → gateway returns HTTP 503. If cache has stale entries beyond TTL but Keycloak is down, serve stale for up to 10 minutes (grace period via `stale-while-revalidate` pattern).

**Algorithm restriction:** Only `RS256` accepted — `alg: none` and symmetric algorithms (`HS256`) are explicitly rejected (OWASP JWT attack mitigation).

**Audience validation:** After decode, verify `aud` claim contains `contextiq-gateway` (configured via `JWT_AUDIENCE` env var).

## Acceptance Criteria

- [ ] JWKS is fetched from Keycloak on first call; subsequent calls within 5 min use cached version (zero HTTP calls)
- [ ] Cache TTL of 300 s is enforced — cache miss triggers re-fetch after TTL expiry
- [ ] Key rotation (new key in JWKS) is handled: cache is busted on signature failure and retry succeeds
- [ ] `alg: none` token raises `MalformedTokenError` — never accepted (unit test asserting rejection)
- [ ] `HS256`-signed token raises `MalformedTokenError` — symmetric algorithms rejected
- [ ] Keycloak JWKS fetch timeout (> 2 s) raises `ServiceUnavailableError`; stale cache served for up to 10 min
- [ ] Token with incorrect `aud` claim raises `InvalidSignatureError` (treated as invalid)

## Dependencies

- TASK-US004-01 (middleware calls `JWKSClient.verify()`)
- EP-014 Keycloak deployment (US-043) — `KEYCLOAK_JWKS_URI` points to live Keycloak in staging

## Definition of Done

- [ ] `cachetools` added to `pyproject.toml`
- [ ] Unit tests use `respx` to mock JWKS endpoint; cover: cache hit, cache miss, key rotation, `alg:none`, `HS256`, timeout
- [ ] `KEYCLOAK_JWKS_URI` and `JWT_AUDIENCE` documented in `.env.example`
- [ ] JWKS fetch latency metric `contextiq_jwks_fetch_duration_seconds` added as Prometheus histogram
- [ ] Integration test: valid Keycloak-issued token passes verification against live staging Keycloak
