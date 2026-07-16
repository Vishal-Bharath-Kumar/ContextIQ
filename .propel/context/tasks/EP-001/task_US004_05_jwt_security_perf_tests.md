# TASK-US004-05 — JWT Validation Performance Hardening and Security Test Suite

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US004-05 |
| User Story | US-004 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Security / QA |
| Priority | P0 |
| Points | 3 |
| Status | In Progress |

## Description

Validate that the JWT authentication path meets the 50 ms latency SLA under load and is hardened against common JWT attack vectors (algorithm confusion, `kid` injection, claim tampering). Provides a security test suite that runs in CI on every PR.

## Implementation Details

**Technology:** Python 3.11+, `pytest`, `pytest-benchmark`, `python-jose`, `respx`, `hypothesis` (for property-based token fuzzing)

**File locations:**
- `tests/gateway/test_jwt_performance.py` — latency benchmarks
- `tests/gateway/test_jwt_security.py` — attack vector tests
- `tests/gateway/fixtures/jwt_factory.py` — token generation helpers for tests

**50 ms latency target — what is measured:**
The 50 ms budget covers the entire `JWKSClient.verify()` call on a cache hit:
- JWKS cache lookup: ~1 ms
- `jose.jwt.decode()` (RSA verify): ~5–15 ms on modern hardware
- `JWTClaims.model_validate()`: ~1 ms
- Total expected: ~10–20 ms → well within budget

**Benchmark test:**
```python
@pytest.mark.benchmark(max_time=2.0)
def test_jwt_verify_latency_cache_hit(benchmark, jwks_client, valid_token):
    """p95 token verification on cache hit must be < 50 ms"""
    result = benchmark(lambda: asyncio.run(jwks_client.verify(valid_token)))
    assert benchmark.stats["mean"] < 0.050   # 50 ms
```

**Security attack test cases:**

| Attack | Test | Expected outcome |
|---|---|---|
| `alg: none` | Token with `"alg": "none"` in header | HTTP 401 `malformed_token` |
| Algorithm confusion (`HS256`) | Token signed with the public key as HMAC secret | HTTP 403 `invalid_signature` |
| `kid` header injection | Token with `"kid": "../../etc/passwd"` | HTTP 401 (no path traversal in JWKS lookup) |
| Expired token | Token with `exp = now() - 1` | HTTP 401 `token_expired` |
| Future `nbf` | Token with `nbf = now() + 3600` | HTTP 401 `token_not_yet_valid` |
| Tampered payload | Modify `sub` claim, keep original signature | HTTP 403 `invalid_signature` |
| Missing `sub` | Token without `sub` claim | HTTP 401 `malformed_token` |
| Oversized token | 64 KB JWT string | HTTP 413 (request too large — from NGINX, not gateway) |
| Role escalation | Token with `"roles": ["ADMIN"]` signed by wrong key | HTTP 403 `invalid_signature` |

**`jwt_factory.py` helpers:**
```python
def make_valid_token(sub: str = "user-001", roles: list[str] = None) -> str: ...
def make_expired_token() -> str: ...
def make_none_alg_token() -> str: ...
def make_hs256_token(public_key_pem: str) -> str: ...  # algorithm confusion attack
def make_tampered_token(sub_override: str) -> str: ...
```

**`hypothesis` fuzz test — random claim mutation:**
```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=2048))
def test_random_token_never_crashes_gateway(random_string):
    """No arbitrary string should cause an unhandled exception"""
    response = client.get("/mcp/sse", headers={"Authorization": f"Bearer {random_string}"})
    assert response.status_code in (400, 401, 403)   # always a structured error, never 500
```

## Acceptance Criteria

- [x] Benchmark test asserts mean JWT verification time (cache hit) < 50 ms in CI environment
- [x] `alg: none` attack token returns HTTP 401 (never accepted)
- [x] `HS256` algorithm confusion attack returns HTTP 403
- [x] `kid` path traversal attempt does not trigger a filesystem read (verified via mock asserting no file-open calls)
- [x] Tampered-payload token returns HTTP 403
- [x] `hypothesis` fuzz test runs 200 examples with zero unhandled exceptions (no 500 responses)
- [x] All 9 security attack tests run in CI as a required status check on every PR

## Dependencies

- TASK-US004-01 (middleware under test)
- TASK-US004-02 (JWKS client — cache warm for benchmark)

## Definition of Done

- [x] `pytest-benchmark` and `hypothesis` added to dev dependencies
- [ ] Security test suite tagged `@pytest.mark.security` and included in CI `pytest -m security` job
- [ ] Benchmark results stored as CI artifact for latency regression tracking
- [ ] All 9 attack vectors green in staging environment with real Keycloak-issued JWKS
- [ ] Security test results reviewed and signed off by security officer before Phase 1 release
