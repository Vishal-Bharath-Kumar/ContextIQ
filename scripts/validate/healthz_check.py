"""
AC-6: Probe GET /healthz on every ContextIQ service endpoint.
All services must return HTTP 200 before this script exits 0.

Usage:
    python scripts/validate/healthz_check.py --env staging
    python scripts/validate/healthz_check.py --env prod

Endpoints are resolved via cluster-internal DNS in CI, or via Ingress
hostname in environments where DNS is available.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Final

import httpx

# Service healthz endpoints resolved via cluster-internal DNS in CI.
# Format: (service_name, url)
ENDPOINTS: Final[dict[str, list[tuple[str, str]]]] = {
    "staging": [
        ("mcp-gateway",  "http://mcp-gateway.contextiq-gateway.svc.cluster.local/healthz"),
        ("agent-worker", "http://agent-worker.contextiq-agents.svc.cluster.local/healthz"),
        ("admin-portal", "http://admin-portal.contextiq-admin.svc.cluster.local/healthz"),
        ("keycloak",     "http://keycloak.contextiq-security.svc.cluster.local/auth/health/ready"),
        ("opa",          "http://opa.contextiq-security.svc.cluster.local:8181/health"),
        ("jaeger",       "http://jaeger.contextiq-observability.svc.cluster.local:16686/"),
    ],
    "prod": [
        ("mcp-gateway",  "https://contextiq.internal/healthz"),
        ("admin-portal", "https://contextiq.internal/admin/healthz"),
        ("keycloak",     "https://contextiq.internal/auth/health/ready"),
    ],
}


async def probe(
    client: httpx.AsyncClient,
    name: str,
    url: str,
) -> tuple[str, bool, int]:
    """Probe a single healthz endpoint.

    Returns:
        (service_name, ok, http_status_code) — status_code is -1 on connection error.
    """
    try:
        response = await client.get(url, timeout=10.0)
        ok = response.status_code == 200
        return name, ok, response.status_code
    except Exception as exc:
        print(f"  ERROR probing {name} at {url}: {exc}")
        return name, False, -1


async def run(env: str) -> int:
    """Probe all endpoints for the given environment.

    Returns:
        0 if all services are healthy, 1 otherwise.
    """
    endpoints = ENDPOINTS.get(env)
    if not endpoints:
        print(f"Unknown environment: {env}. Available: {list(ENDPOINTS)}")
        return 1

    async with httpx.AsyncClient(verify=True) as client:
        results = await asyncio.gather(
            *[probe(client, name, url) for name, url in endpoints]
        )

    failures = 0
    for name, ok, code in results:
        status = "OK" if ok else f"FAIL (HTTP {code})"
        print(f"  {name:<30s} {status}")
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures} service(s) failed healthz check.")
        return 1

    print(f"\nAll {len(results)} services healthy.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ContextIQ healthz probe")
    parser.add_argument("--env", default="staging", choices=list(ENDPOINTS))
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.env)))
