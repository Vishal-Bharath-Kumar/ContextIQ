# TASK-US004-01 — ASGI JWT Authentication Middleware

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US004-01 |
| User Story | US-004 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend / Security |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Implement an ASGI middleware that intercepts every inbound HTTP and WebSocket request, extracts the `Authorization: Bearer <token>` header, and enforces authentication before any handler executes. Requests with missing, malformed, expired, or invalid-signature tokens are rejected with the appropriate HTTP status code without reaching the tool handlers.

## Implementation Details

**Technology:** Python 3.11+, `python-jose` (JWT decode + signature verification), FastAPI ASGI middleware

**File locations:**
- `src/gateway/middleware/jwt_auth.py` — `JWTAuthMiddleware` ASGI class
- `src/gateway/schemas/auth_types.py` — `JWTClaims`, `AuthError` models
- `tests/gateway/test_jwt_auth_middleware.py`

**Middleware decision tree:**

```
Inbound request
│
├─ No Authorization header → HTTP 401
│    {"error": "missing_token", "message": "Authorization header required"}
│
├─ Header present but not "Bearer <token>" format → HTTP 401
│    {"error": "invalid_token_format"}
│
├─ Token decode fails (malformed JWT) → HTTP 401
│    {"error": "malformed_token"}
│
├─ Signature verification fails → HTTP 403
│    {"error": "invalid_signature"}
│
├─ Token expired (`exp` claim) → HTTP 401
│    WWW-Authenticate: Bearer error="invalid_token", error_description="Token expired"
│    {"error": "token_expired"}
│
└─ Valid token → inject claims into ASGI scope state → next()
```

**Middleware implementation:**
```python
class JWTAuthMiddleware:
    def __init__(self, app: ASGIApp, jwks_client: JWKSClient):
        self.app = app
        self.jwks_client = jwks_client

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Skip health check — no auth required
        if scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return

        token = self._extract_bearer_token(scope)
        if token is None:
            await self._send_401(send, "missing_token")
            return

        try:
            claims = await self.jwks_client.verify(token)
        except ExpiredTokenError:
            await self._send_401_expired(send)
            return
        except InvalidSignatureError:
            await self._send_403(send, "invalid_signature")
            return
        except MalformedTokenError:
            await self._send_401(send, "malformed_token")
            return

        scope.setdefault("state", {})
        scope["state"]["jwt_claims"] = claims
        await self.app(scope, receive, send)
```

**`/healthz` bypass:** Kubernetes liveness/readiness probes must not require auth.

**WebSocket handling:** For `ws://` / `wss://` connections, the token may arrive in the query string (`?token=...`) as a fallback since browser WebSocket APIs cannot set custom headers. Check `Authorization` header first; fall back to `token` query param (mark as lower-security, log at DEBUG).

## Acceptance Criteria

- [ ] Request with no `Authorization` header returns HTTP 401 with `{"error": "missing_token"}`
- [ ] Request with `Authorization: Basic ...` returns HTTP 401 with `{"error": "invalid_token_format"}`
- [ ] Request with a structurally valid JWT but wrong signature returns HTTP 403
- [ ] Request with an expired JWT returns HTTP 401 with `WWW-Authenticate: Bearer error="invalid_token", error_description="Token expired"`
- [ ] Valid JWT passes through and `scope["state"]["jwt_claims"]` is populated
- [ ] `GET /healthz` bypasses authentication and returns HTTP 200 regardless of auth header
- [ ] Unit tests cover all 5 rejection paths and the valid-token pass-through

## Dependencies

- TASK-US001-01 (FastAPI app middleware stack)
- TASK-US004-02 (JWKS client injected into middleware)

## Definition of Done

- [ ] Middleware registered first in FastAPI middleware stack (before all other middleware)
- [ ] Unit coverage ≥ 95% for `middleware/jwt_auth.py`
- [ ] `python-jose[cryptography]` pinned in `pyproject.toml`
- [ ] `mypy --strict` passes; OWASP A07 (Identification and Authentication Failures) checklist reviewed
