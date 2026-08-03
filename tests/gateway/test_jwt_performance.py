"""
JWT Validation Performance Benchmarks — TASK-US004-05.

Validates that the JWT verification path meets the 50 ms latency SLA under
realistic conditions (cache hit).

SLA budget breakdown (cache hit):
  - JWKS TTLCache lookup  : ~1 ms
  - jose.jwt.decode (RSA) : ~5–15 ms on modern hardware
  - JWTClaims.model_validate: ~1 ms
  - Total expected        : ~10–20 ms → well within 50 ms budget

Run benchmarks:
    pytest tests/gateway/test_jwt_performance.py --benchmark-only -v

Store CI artifacts (in CI pipeline):
    pytest tests/gateway/test_jwt_performance.py --benchmark-json=benchmark-results.json
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import pytest
import respx
import httpx

from tests.gateway.fixtures.jwt_factory import (
    AUDIENCE,
    JWKS_URI,
    ISSUER,
    SESSION_JWK,
    SESSION_JWKS,
    SESSION_PRIVATE_PEM,
    make_valid_token,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def valid_token() -> str:
    """A freshly-signed valid RS256 token for benchmarking."""
    return make_valid_token(sub="bench-user", roles=["developer"])


@pytest.fixture(scope="module")
def jwks_client_with_warm_cache() -> Any:
    """
    JWKSClient whose JWKS cache is pre-warmed with SESSION_JWKS so that
    benchmark calls exercise the cache-hit path without any HTTP I/O.
    """
    from src.gateway.auth.jwks_client import JWKSClient

    mock_http = httpx.AsyncClient()
    client = JWKSClient(jwks_uri=JWKS_URI, audience=AUDIENCE, http_client=mock_http)

    # Pre-warm the TTLCache directly — bypasses the async _fetch_jwks path
    # so the benchmark only measures verify() with an already-populated cache.
    client._cache["jwks"] = SESSION_JWKS
    client._stale_jwks = SESSION_JWKS
    client._stale_fetched_at = time.monotonic()
    return client


# ---------------------------------------------------------------------------
# Benchmark test — 50 ms SLA on cache hit
# ---------------------------------------------------------------------------

def test_jwt_verify_latency_cache_hit(
    benchmark: Any,
    jwks_client_with_warm_cache: Any,
    valid_token: str,
) -> None:
    """
    p95 token verification time on cache hit must be < 50 ms (mean < 50 ms).

    benchmark.stats["mean"] is expressed in seconds; 0.050 == 50 ms.

    This test is intentionally synchronous so pytest-benchmark can measure
    pure CPU time.  asyncio.run() overhead is negligible (< 0.1 ms) and is
    deliberately included because it represents the real call path.
    """
    result = benchmark(
        lambda: asyncio.run(jwks_client_with_warm_cache.verify(valid_token))
    )

    # Verify the token was actually decoded (not a no-op path)
    assert result is not None
    assert result.sub == "bench-user"

    # SLA assertion — mean per-call latency must be under 50 ms
    mean_seconds: float = benchmark.stats["mean"]
    assert mean_seconds < 0.050, (
        f"JWT verify mean latency {mean_seconds * 1000:.2f} ms exceeds 50 ms SLA"
    )


# ---------------------------------------------------------------------------
# Benchmark test — cache hit vs cache miss comparison (informational)
# ---------------------------------------------------------------------------

@pytest.mark.benchmark(group="jwt-latency")
def test_jwt_verify_latency_cache_hit_group(
    benchmark: Any,
    jwks_client_with_warm_cache: Any,
    valid_token: str,
) -> None:
    """Grouped benchmark — cache hit path.  Used for regression comparison."""
    benchmark.group = "jwt-latency"
    benchmark.name = "cache_hit"
    result = benchmark(
        lambda: asyncio.run(jwks_client_with_warm_cache.verify(valid_token))
    )
    assert result.sub == "bench-user"
    assert benchmark.stats["mean"] < 0.050


@pytest.mark.benchmark(group="jwt-latency")
def test_jwt_verify_latency_cache_miss(benchmark: Any, valid_token: str) -> None:
    """
    Benchmark the cache-miss path (first verify call, JWKS endpoint mocked).

    The network call is intercepted by respx so wall time is dominated by
    the RSA decode + HTTP round-trip simulation (< 5 ms with a mocked endpoint).
    This benchmark is *informational* only — there is no SLA on cold-start latency.
    """
    with respx.mock(base_url=JWKS_URI) as mock_router:
        mock_router.get("").mock(return_value=httpx.Response(200, json=SESSION_JWKS))

        from src.gateway.auth.jwks_client import JWKSClient

        def _verify() -> Any:
            client = JWKSClient(jwks_uri=JWKS_URI, audience=AUDIENCE)
            return asyncio.run(client.verify(valid_token))

        result = benchmark(_verify)

    assert result is not None
    assert result.sub == "bench-user"
