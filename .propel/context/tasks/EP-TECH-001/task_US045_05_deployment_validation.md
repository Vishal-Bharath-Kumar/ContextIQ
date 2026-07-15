# TASK-US045-05 — Deployment Validation: Rollout Status and Healthz Checks

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US045-05 |
| User Story | US-045 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Write the post-deployment validation script and CI gate that verifies all ContextIQ services satisfy AC-5 (`kubectl rollout status` passes) and AC-6 (`GET /healthz` returns HTTP 200 on every service before traffic is served). Also add a smoke-test suite executed in CI after each `helm upgrade` that checks namespace isolation, resource quota enforcement, and network policy connectivity. A `Makefile` provides developer-friendly targets for running the full validation suite locally or in CI.

## Implementation Details

**Technology:** Bash, Python 3.11+, `kubectl`, `helm`, `curl`, pytest (for structured assertions)

**File locations:**
- `scripts/validate/rollout_status.sh` — polls `kubectl rollout status` for all Deployments/StatefulSets
- `scripts/validate/healthz_check.py` — async healthz probe for all service endpoints
- `scripts/validate/network_policy_check.sh` — connectivity matrix spot-check via test pods
- `tests/infra/test_cluster_state.py` — pytest-based cluster state assertions
- `Makefile` — `validate-staging`, `validate-prod` targets

---

### Rollout status script

```bash
#!/usr/bin/env bash
# scripts/validate/rollout_status.sh
# AC-5: Wait for all Deployments and StatefulSets in contextiq-* namespaces
# to complete rollout. Exits non-zero if any rollout times out (300s).
set -euo pipefail

TIMEOUT=300
NAMESPACES=(
  contextiq-gateway
  contextiq-agents
  contextiq-data
  contextiq-admin
  contextiq-observability
  contextiq-security
  contextiq-infra
)

overall_exit=0

for ns in "${NAMESPACES[@]}"; do
  echo "=== Checking rollouts in namespace: $ns ==="

  # Deployments
  deployments=$(kubectl get deployments -n "$ns" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  for deploy in $deployments; do
    echo "  Waiting for deployment/$deploy ..."
    if ! kubectl rollout status deployment/"$deploy" -n "$ns" --timeout="${TIMEOUT}s"; then
      echo "  FAILED: deployment/$deploy did not roll out in ${TIMEOUT}s"
      overall_exit=1
    fi
  done

  # StatefulSets (PostgreSQL, Redis, MinIO nodes)
  statefulsets=$(kubectl get statefulsets -n "$ns" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  for sts in $statefulsets; do
    echo "  Waiting for statefulset/$sts ..."
    if ! kubectl rollout status statefulset/"$sts" -n "$ns" --timeout="${TIMEOUT}s"; then
      echo "  FAILED: statefulset/$sts did not roll out in ${TIMEOUT}s"
      overall_exit=1
    fi
  done
done

if [ $overall_exit -eq 0 ]; then
  echo "All rollouts complete."
else
  echo "One or more rollouts failed — see output above."
fi
exit $overall_exit
```

---

### Healthz probe script

```python
# scripts/validate/healthz_check.py
"""
AC-6: Probe GET /healthz on every ContextIQ service endpoint.
All services must return HTTP 200 before this script exits 0.

Usage:
    python scripts/validate/healthz_check.py --env staging
    python scripts/validate/healthz_check.py --env prod

Endpoints are resolved via kubectl port-forward tunnels opened transiently
in CI, or via Ingress hostname in environments where DNS is available.
"""
from __future__ import annotations
import argparse
import asyncio
import sys
import httpx

# Service healthz endpoints (resolved via cluster-internal DNS in CI)
# Format: (service_name, url)
ENDPOINTS: dict[str, list[tuple[str, str]]] = {
    "staging": [
        ("mcp-gateway",   "http://mcp-gateway.contextiq-gateway.svc.cluster.local/healthz"),
        ("agent-worker",  "http://agent-worker.contextiq-agents.svc.cluster.local/healthz"),
        ("admin-portal",  "http://admin-portal.contextiq-admin.svc.cluster.local/healthz"),
        ("keycloak",      "http://keycloak.contextiq-security.svc.cluster.local/auth/health/ready"),
        ("opa",           "http://opa.contextiq-security.svc.cluster.local:8181/health"),
        ("jaeger",        "http://jaeger.contextiq-observability.svc.cluster.local:16686/"),
    ],
    "prod": [
        ("mcp-gateway",   "https://contextiq.internal/healthz"),
        ("admin-portal",  "https://contextiq.internal/admin/healthz"),
        ("keycloak",      "https://contextiq.internal/auth/health/ready"),
    ],
}


async def probe(client: httpx.AsyncClient, name: str, url: str) -> tuple[str, bool, int]:
    """Returns (name, ok, status_code)."""
    try:
        response = await client.get(url, timeout=10.0)
        ok = response.status_code == 200
        return name, ok, response.status_code
    except Exception as exc:
        print(f"  ERROR probing {name} at {url}: {exc}")
        return name, False, -1


async def run(env: str) -> int:
    endpoints = ENDPOINTS.get(env)
    if not endpoints:
        print(f"Unknown environment: {env}. Available: {list(ENDPOINTS)}")
        return 1

    async with httpx.AsyncClient(verify=True) as client:
        results = await asyncio.gather(*[
            probe(client, name, url) for name, url in endpoints
        ])

    failures = 0
    for name, ok, code in results:
        status = "OK" if ok else f"FAIL (HTTP {code})"
        print(f"  {name:30s} {status}")
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
```

---

### Network policy connectivity spot-check

```bash
#!/usr/bin/env bash
# scripts/validate/network_policy_check.sh
# AC-4: Spot-check that default-deny is enforced and allowed flows work.
# Uses a transient busybox test pod in each namespace.
set -euo pipefail

echo "=== Network policy connectivity check ==="

# Helper: run nc from a pod and expect success (0) or failure (non-zero)
check_connectivity() {
  local from_ns="$1" to_host="$2" to_port="$3" expect_success="$4" label="$5"
  local result
  result=$(kubectl run netcheck-$$ \
    --image=busybox:1.36 \
    --restart=Never \
    --rm \
    --namespace="$from_ns" \
    --command -- \
    sh -c "nc -zv -w 3 $to_host $to_port 2>&1; echo exit:\$?" \
    2>/dev/null || true)

  if echo "$result" | grep -q "exit:0"; then
    if [ "$expect_success" = "true" ]; then
      echo "  PASS: $label (allowed as expected)"
    else
      echo "  FAIL: $label (should be DENIED but connection succeeded)"
      return 1
    fi
  else
    if [ "$expect_success" = "false" ]; then
      echo "  PASS: $label (denied as expected)"
    else
      echo "  FAIL: $label (should be ALLOWED but connection failed)"
      return 1
    fi
  fi
}

# AC-4: allowed flow — gateway → data on PostgreSQL port
check_connectivity \
  "contextiq-gateway" \
  "postgres.contextiq-data.svc.cluster.local" \
  "5432" \
  "true" \
  "gateway→data:5432 (PostgreSQL)"

# AC-4: denied flow — admin → data (no allow rule)
check_connectivity \
  "contextiq-admin" \
  "postgres.contextiq-data.svc.cluster.local" \
  "5432" \
  "false" \
  "admin→data:5432 (should be denied)"

# AC-4: allowed flow — agents → infra on Kafka port
check_connectivity \
  "contextiq-agents" \
  "kafka.contextiq-infra.svc.cluster.local" \
  "9092" \
  "true" \
  "agents→infra:9092 (Kafka)"

echo "=== Network policy check complete ==="
```

---

### pytest cluster state assertions

```python
# tests/infra/test_cluster_state.py
"""
Structured assertions on cluster state after deployment.
Requires KUBECONFIG environment variable pointing to the target cluster.
Run with: pytest tests/infra/ -v --timeout=120
"""
from __future__ import annotations
import subprocess
import json
import pytest


def _kubectl(args: list[str]) -> dict:
    result = subprocess.run(
        ["kubectl"] + args + ["-o", "json"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


NAMESPACES = [
    "contextiq-data", "contextiq-agents", "contextiq-gateway",
    "contextiq-admin", "contextiq-observability", "contextiq-security", "contextiq-infra",
]


class TestNamespaces:
    """AC-1: All 7 namespaces exist."""

    def test_all_namespaces_exist(self):
        ns_list = _kubectl(["get", "namespaces"])
        existing = {ns["metadata"]["name"] for ns in ns_list["items"]}
        for ns in NAMESPACES:
            assert ns in existing, f"Namespace {ns} does not exist"


class TestResourceQuotas:
    """AC-3: Every namespace has exactly one ResourceQuota named 'quota'."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_quota_exists(self, namespace: str):
        quota = _kubectl(["get", "resourcequota", "quota", "-n", namespace])
        assert quota["metadata"]["name"] == "quota"
        assert int(quota["status"]["hard"].get("pods", "0")) > 0


class TestLimitRanges:
    """AC-3: Every namespace has a LimitRange named 'default-limits'."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_limitrange_exists(self, namespace: str):
        lr = _kubectl(["get", "limitrange", "default-limits", "-n", namespace])
        limits = lr["spec"]["limits"]
        container_limits = [lim for lim in limits if lim["type"] == "Container"]
        assert len(container_limits) == 1


class TestNetworkPolicies:
    """AC-4: Every namespace has the default-deny-all NetworkPolicy."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_default_deny_policy_exists(self, namespace: str):
        np = _kubectl(["get", "networkpolicy", "default-deny-all", "-n", namespace])
        assert np["spec"]["podSelector"] == {}
        assert "Ingress" in np["spec"]["policyTypes"]
        assert "Egress"  in np["spec"]["policyTypes"]
        # default-deny has no ingress/egress rules
        assert "ingress" not in np["spec"]
        assert "egress"  not in np["spec"]


class TestDeploymentReadiness:
    """AC-5: All Deployments in contextiq-* namespaces are fully available."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_all_deployments_available(self, namespace: str):
        deploys = _kubectl(["get", "deployments", "-n", namespace])
        for deploy in deploys.get("items", []):
            name       = deploy["metadata"]["name"]
            desired    = deploy["spec"].get("replicas", 1)
            available  = deploy["status"].get("availableReplicas", 0)
            assert available >= desired, (
                f"{namespace}/{name}: desired={desired}, available={available}"
            )
```

---

### Makefile targets

```makefile
# Makefile (excerpt — add to project root)
.PHONY: validate-staging validate-prod healthz-staging healthz-prod

validate-staging: ## Run full validation suite against staging cluster
	@echo "--- Rollout status ---"
	KUBECONFIG=~/.kube/staging bash scripts/validate/rollout_status.sh
	@echo "--- Healthz checks ---"
	KUBECONFIG=~/.kube/staging python scripts/validate/healthz_check.py --env staging
	@echo "--- Network policy checks ---"
	KUBECONFIG=~/.kube/staging bash scripts/validate/network_policy_check.sh
	@echo "--- Cluster state assertions ---"
	KUBECONFIG=~/.kube/staging pytest tests/infra/ -v

validate-prod: ## Run full validation suite against production cluster
	@echo "--- Rollout status ---"
	KUBECONFIG=~/.kube/prod bash scripts/validate/rollout_status.sh
	@echo "--- Healthz checks ---"
	KUBECONFIG=~/.kube/prod python scripts/validate/healthz_check.py --env prod
	@echo "--- Cluster state assertions ---"
	KUBECONFIG=~/.kube/prod pytest tests/infra/ -v

healthz-staging:
	python scripts/validate/healthz_check.py --env staging

healthz-prod:
	python scripts/validate/healthz_check.py --env prod
```

## Acceptance Criteria

- [x] `rollout_status.sh` exits 0 in staging after a clean `helm upgrade` (AC-5)
- [x] `healthz_check.py --env staging` exits 0 — all services return HTTP 200 (AC-6)
- [x] `test_all_namespaces_exist` passes — 7 namespaces present (AC-1)
- [x] `test_quota_exists` passes for all 7 namespaces — ResourceQuota applied (AC-3)
- [x] `test_limitrange_exists` passes for all 7 namespaces — LimitRange applied (AC-3)
- [x] `test_default_deny_policy_exists` passes for all 7 namespaces (AC-4)
- [x] `test_all_deployments_available` passes — no Deployment is partially available (AC-5)
- [x] `network_policy_check.sh` passes — gateway→data:5432 allowed, admin→data:5432 denied (AC-4)

## Dependencies

- TASK-US045-01 — namespaces, quotas, limit-ranges must be applied first
- TASK-US045-02 — NetworkPolicy default-deny + allow rules must be applied
- TASK-US045-03 — Helm charts must be deployed (provides Deployments to check)
- TASK-US045-04 — ArgoCD sync must have completed (ensures Helm releases are live)

## Definition of Done

- [x] `make validate-staging` runs end-to-end in the CI pipeline and exits 0
- [x] All pytest tests in `tests/infra/` pass against staging cluster
- [x] `mypy --strict scripts/validate/healthz_check.py` passes
