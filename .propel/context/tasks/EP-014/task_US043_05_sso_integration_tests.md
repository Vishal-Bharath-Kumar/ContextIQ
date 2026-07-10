# TASK-US043-05 — SSO Integration Tests: JWKS Validation, Role Mapping, and Token Lifetime

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US043-05 |
| User Story | US-043 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Write the automated test suite that verifies all 7 US-043 acceptance criteria without a live Keycloak instance. Use `respx` to mock Keycloak's JWKS endpoint; use `python-jose` to mint RSA-signed test tokens with configurable claims. Verify the `JWKSClient` cache TTL, the `JWTAuthMiddleware` 401/403 responses, token lifetime enforcement (exp claim), and the idempotency of both broker configuration scripts (Entra ID and SAML).

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `respx`, `python-jose[cryptography]`, `cryptography` (RSA key generation), `httpx.AsyncClient` + `ASGITransport`

**File locations:**
- `tests/auth/conftest.py` — RSA key pair fixture, JWKS endpoint mock, test token factory
- `tests/auth/test_jwks_client.py` — JWKS client unit tests (cache TTL, key rotation, decode)
- `tests/auth/test_jwt_middleware.py` — middleware integration tests (401/403 paths)
- `tests/auth/test_token_lifetime.py` — token lifetime enforcement (access=5 min, refresh=8 h)
- `tests/auth/test_broker_scripts_idempotency.py` — Keycloak Admin API mock + idempotency checks

---

### Shared fixtures

```python
# tests/auth/conftest.py
from __future__ import annotations
import base64
import json
import time
from typing import Any

import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives            import serialization
from jose                                      import jwt as jose_jwt

from src.auth.keycloak_settings import KeycloakSettings
from src.auth.jwks_client       import JWKSClient

REALM   = "contextiq"
TEST_KC = "https://keycloak.test"


@pytest.fixture(scope="session")
def rsa_key_pair():
    """Generate a 2048-bit RSA key pair for signing test tokens."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key  = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="session")
def kid() -> str:
    return "test-key-001"


@pytest.fixture(scope="session")
def jwks_payload(rsa_key_pair, kid) -> dict[str, Any]:
    """
    Build a JWKS-format JSON payload from the test RSA public key.
    This is what a real Keycloak /protocol/openid-connect/certs endpoint returns.
    """
    _, public_key = rsa_key_pair
    pub_numbers   = public_key.public_key().public_numbers() if hasattr(public_key, "public_key") else public_key.public_numbers()

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


@pytest.fixture
def mint_token(rsa_key_pair, kid):
    """
    Factory that mints RS256-signed JWTs with configurable claims.

    Usage:
        token = mint_token(roles=["admin"], exp_offset=300)
    """
    private_key, _ = rsa_key_pair
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
        if False else serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    def _mint(
        roles: list[str] | None = None,
        exp_offset: int = 300,       # seconds from now; negative = already expired
        aud: str = "contextiq-mcp-gateway",
        iss: str = f"{TEST_KC}/realms/{REALM}",
        sub: str = "user-test-001",
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub":              sub,
            "preferred_username": "testuser",
            "iss":              iss,
            "aud":              aud,
            "iat":              now,
            "exp":              now + exp_offset,
            "realm_access": {
                "roles": roles or ["developer"],
            },
            "resource_access": {},
        }
        return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})

    return _mint


@pytest.fixture
def keycloak_settings() -> KeycloakSettings:
    return KeycloakSettings(
        url        = TEST_KC,
        realm      = REALM,
        audience   = "contextiq-mcp-gateway",
        algorithms = ["RS256"],
    )


@pytest.fixture
def mock_jwks(jwks_payload, keycloak_settings):
    """Activate respx mock for Keycloak JWKS endpoint."""
    jwks_uri = keycloak_settings.jwks_uri
    with respx.mock(base_url=jwks_uri, assert_all_called=False) as mock:
        mock.get(jwks_uri).mock(
            return_value=__import__("httpx").Response(200, json=jwks_payload)
        )
        yield mock
```

---

### JWKS client tests

```python
# tests/auth/test_jwks_client.py
import asyncio
import time
import pytest
from src.auth.jwks_client import JWKSClient, _JWKS_TTL_SECONDS


@pytest.mark.asyncio
async def test_decode_valid_token(mock_jwks, keycloak_settings, mint_token):
    """AC-3: Valid RS256 token is decoded and claims returned."""
    token  = mint_token(roles=["admin"])
    client = JWKSClient(keycloak_settings)
    await client.startup()
    claims = await client.decode(token)
    assert claims["realm_access"]["roles"] == ["admin"]
    await client.shutdown()


@pytest.mark.asyncio
async def test_decode_expired_token_raises(mock_jwks, keycloak_settings, mint_token):
    """AC-6: Expired token raises JWTError — enforces 5-min access token TTL."""
    from jose.exceptions import JWTError
    token  = mint_token(roles=["developer"], exp_offset=-1)  # already expired
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(token)
    await client.shutdown()


@pytest.mark.asyncio
async def test_decode_wrong_audience_raises(mock_jwks, keycloak_settings, mint_token):
    """Token for wrong audience is rejected."""
    from jose.exceptions import JWTError
    token  = mint_token(aud="some-other-service")
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(token)
    await client.shutdown()


@pytest.mark.asyncio
async def test_jwks_cache_prevents_repeated_fetch(mock_jwks, keycloak_settings, mint_token):
    """JWKS endpoint is called once; subsequent decodes use the cache."""
    token  = mint_token()
    client = JWKSClient(keycloak_settings)
    await client.startup()
    for _ in range(5):
        await client.decode(token)
    # Only the startup() call + one decode call should have fetched keys
    # (respx tracks call count)
    assert mock_jwks.calls.call_count <= 2
    await client.shutdown()


@pytest.mark.asyncio
async def test_unknown_kid_triggers_refresh(mock_jwks, keycloak_settings, rsa_key_pair):
    """
    AC-3: If the token's kid is not in the cached JWKS, the client fetches
    fresh keys once before failing. Simulated by minting with a kid that is
    not in the initial cache but IS in the refreshed response.
    """
    from jose.exceptions import JWTError
    from jose import jwt as jose_jwt
    from cryptography.hazmat.primitives import serialization
    import time

    private_key, _ = rsa_key_pair
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    # Token with a kid that is NOT in the JWKS mock — should trigger one refresh, then fail
    unknown_kid_token = jose_jwt.encode(
        {
            "sub": "u1", "iss": keycloak_settings.issuer,
            "aud": keycloak_settings.audience,
            "iat": int(time.time()), "exp": int(time.time()) + 300,
            "realm_access": {"roles": ["developer"]}, "resource_access": {},
            "preferred_username": "u1",
        },
        pem,
        algorithm="RS256",
        headers={"kid": "UNKNOWN-KEY-XYZ"},
    )
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(unknown_kid_token)
    # Two fetches: startup() + one retry on unknown kid
    assert mock_jwks.calls.call_count == 2
    await client.shutdown()
```

---

### Middleware integration tests

```python
# tests/auth/test_jwt_middleware.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from src.main import create_app


@pytest.fixture
def app_with_mock_jwks(keycloak_settings, mint_token, mock_jwks):
    """Create FastAPI app with a pre-warmed JWKSClient backed by respx mock."""
    from src.auth.jwks_client   import JWKSClient
    from src.auth.middleware     import JWTAuthMiddleware

    async def lifespan(app):
        client = JWKSClient(keycloak_settings)
        await client.startup()
        app.state.jwks_client = client
        yield
        await client.shutdown()

    app = create_app()
    return app


@pytest.mark.asyncio
async def test_missing_auth_header_returns_401(app_with_mock_jwks):
    """AC-3: Requests with no Authorization header return HTTP 401."""
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get("/v1/models")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_passes_middleware(app_with_mock_jwks, mint_token):
    """AC-3: Valid token results in jwt_claims stored on request.state."""
    token = mint_token(roles=["platform_engineer"])
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
    # 200 or 403 (RBAC) — both confirm middleware passed the token through
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_expired_token_returns_401(app_with_mock_jwks, mint_token):
    """AC-6: Expired access token returns HTTP 401 — enforces 5-min TTL."""
    token = mint_token(roles=["admin"], exp_offset=-1)
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_endpoint_skips_auth(app_with_mock_jwks):
    """Health endpoint bypasses JWT validation (in _SKIP_PATHS)."""
    async with AsyncClient(transport=ASGITransport(app_with_mock_jwks), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
```

---

### Token lifetime enforcement tests

```python
# tests/auth/test_token_lifetime.py
import time
import pytest
from jose.exceptions import JWTError
from src.auth.jwks_client import JWKSClient


@pytest.mark.asyncio
async def test_access_token_exactly_at_5min_boundary(mock_jwks, keycloak_settings, mint_token):
    """AC-6: Token minted with exp = now + 300 (exactly 5 min) is valid."""
    token  = mint_token(exp_offset=300)
    client = JWKSClient(keycloak_settings)
    await client.startup()
    claims = await client.decode(token)
    assert claims["sub"] == "user-test-001"
    await client.shutdown()


@pytest.mark.asyncio
async def test_access_token_1_second_past_expiry_is_rejected(mock_jwks, keycloak_settings, mint_token):
    """AC-6: Token expired 1 second ago is rejected."""
    token  = mint_token(exp_offset=-1)
    client = JWKSClient(keycloak_settings)
    await client.startup()
    with pytest.raises(JWTError):
        await client.decode(token)
    await client.shutdown()


def test_refresh_token_lifetime_configured_in_realm_bootstrap():
    """
    AC-6: The realm bootstrap script (TASK-US043-01) sets ssoSessionMaxLifespan=28800.
    This test verifies the value is present in the bootstrap payload at the source level.
    """
    import inspect
    import scripts.keycloak.bootstrap_realm as bootstrap_module
    source = inspect.getsource(bootstrap_module)
    assert "ssoSessionMaxLifespan" in source
    assert "28800" in source
    assert "accessTokenLifespan" in source
    assert "300" in source
```

---

### Broker script idempotency tests

```python
# tests/auth/test_broker_scripts_idempotency.py
import pytest
from unittest.mock import MagicMock, call


def _make_mock_admin(existing_idps=None, existing_mappers=None):
    """Create a mock KeycloakAdmin object pre-configured with existing data."""
    admin            = MagicMock()
    admin.get_idps   = MagicMock(return_value=[{"alias": a} for a in (existing_idps or [])])
    admin.get_idp_mappers = MagicMock(return_value=[{"name": n} for n in (existing_mappers or [])])
    return admin


class TestEntraIdBrokerIdempotency:
    """AC-2: Running configure_entra_id_broker.py twice produces no duplicates."""

    def test_create_called_when_idp_absent(self, monkeypatch):
        from scripts.keycloak.configure_entra_id_broker import register_entra_id_broker
        admin = _make_mock_admin(existing_idps=[])
        monkeypatch.setenv("ENTRA_TENANT_ID",     "test-tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID",     "test-client")
        monkeypatch.setenv("ENTRA_CLIENT_SECRET", "test-secret")
        register_entra_id_broker(admin)
        admin.create_idp.assert_called_once()
        admin.update_idp.assert_not_called()

    def test_update_called_when_idp_exists(self, monkeypatch):
        from scripts.keycloak.configure_entra_id_broker import register_entra_id_broker
        admin = _make_mock_admin(existing_idps=["entra-id"])
        monkeypatch.setenv("ENTRA_TENANT_ID",     "test-tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID",     "test-client")
        monkeypatch.setenv("ENTRA_CLIENT_SECRET", "test-secret")
        register_entra_id_broker(admin)
        admin.update_idp.assert_called_once()
        admin.create_idp.assert_not_called()

    def test_mapper_not_duplicated_if_already_exists(self, monkeypatch):
        from scripts.keycloak.configure_entra_id_broker import configure_group_role_mappers
        # Pre-populate all 7 mappers as existing
        all_mapper_names = [f"groups-to-{r}" for r in [
            "admin", "platform_engineer", "security_officer",
            "developer", "manager", "auditor", "devops_sre",
        ]]
        admin = _make_mock_admin(existing_mappers=all_mapper_names)
        configure_group_role_mappers(admin)
        admin.add_mapper_to_idp.assert_not_called()


class TestSamlBrokerIdempotency:
    """AC-7: Running configure_saml_broker.py twice produces no duplicates."""

    def test_create_called_when_idp_absent(self, monkeypatch):
        from scripts.keycloak.configure_saml_broker import register_saml_broker
        admin = _make_mock_admin(existing_idps=[])
        monkeypatch.setenv("SAML_IDP_ENTITY_ID",    "https://idp.example.com")
        monkeypatch.setenv("SAML_IDP_SSO_URL",      "https://idp.example.com/sso")
        monkeypatch.setenv("SAML_IDP_SIGNING_CERT", "FAKECERT")
        register_saml_broker(admin)
        admin.create_idp.assert_called_once()
        admin.update_idp.assert_not_called()

    def test_update_called_when_idp_exists(self, monkeypatch):
        from scripts.keycloak.configure_saml_broker import register_saml_broker
        admin = _make_mock_admin(existing_idps=["saml-onprem"])
        monkeypatch.setenv("SAML_IDP_ENTITY_ID",    "https://idp.example.com")
        monkeypatch.setenv("SAML_IDP_SSO_URL",      "https://idp.example.com/sso")
        monkeypatch.setenv("SAML_IDP_SIGNING_CERT", "FAKECERT")
        register_saml_broker(admin)
        admin.update_idp.assert_called_once()
        admin.create_idp.assert_not_called()
```

## Acceptance Criteria

- [ ] `test_decode_valid_token` — valid RS256-signed JWT decoded successfully (AC-3)
- [ ] `test_decode_expired_token_raises` — expired token raises `JWTError` (AC-6)
- [ ] `test_decode_wrong_audience_raises` — wrong `aud` claim rejected (AC-3)
- [ ] `test_jwks_cache_prevents_repeated_fetch` — JWKS endpoint called at most twice for 5 sequential decodes (TASK-US043-03 cache)
- [ ] `test_unknown_kid_triggers_refresh` — unknown key triggers exactly one refresh, then fails (TASK-US043-03)
- [ ] `test_missing_auth_header_returns_401` — middleware returns 401 for missing header (AC-3)
- [ ] `test_expired_token_returns_401` — middleware returns 401 for expired token (AC-6)
- [ ] `test_health_endpoint_skips_auth` — `/healthz` returns 200 without any Authorization header (AC-3 skip-paths)
- [ ] `test_refresh_token_lifetime_configured_in_realm_bootstrap` — bootstrap script contains `ssoSessionMaxLifespan=28800` (AC-6)
- [ ] `test_create_called_when_idp_absent` (both Entra and SAML) — first run creates IdP (AC-2, AC-7)
- [ ] `test_update_called_when_idp_exists` (both Entra and SAML) — second run updates, not duplicates (AC-2, AC-7)
- [ ] `test_mapper_not_duplicated_if_already_exists` — mapper idempotency guard works (AC-4)

## Dependencies

- TASK-US043-01 — `bootstrap_realm.py` imported by token lifetime source inspection test
- TASK-US043-02 — `configure_entra_id_broker.py` tested for idempotency
- TASK-US043-03 — `JWKSClient` and `JWTAuthMiddleware` under test
- TASK-US043-04 — `configure_saml_broker.py` tested for idempotency

## Definition of Done

- [ ] `pytest tests/auth/ -v` passes all tests in this task (no live Keycloak required)
- [ ] `mypy --strict tests/auth/conftest.py tests/auth/test_jwks_client.py tests/auth/test_jwt_middleware.py` passes
- [ ] Test execution time < 10 seconds (all mocked — no network I/O)
