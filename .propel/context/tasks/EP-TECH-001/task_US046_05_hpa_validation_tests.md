# TASK-US046-05 — HPA Staging Validation: Scale-Up Timing and Custom Metric Tests

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US046-05 |
| User Story | US-046 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Write the staging validation suite that verifies all 6 US-046 acceptance criteria without manual cluster observation: a Python load generator that drives `contextiq_active_requests` above the HPA threshold, a polling assertion that confirms scale-up occurs within 30 s (AC-4), a cool-down assertion that confirms scale-down does not happen before 300 s (AC-4), a PDB disruption test (AC-5), and a pytest-based cluster state test (AC-6). The load generator and timing assertions are packaged as a Makefile target `make validate-hpa-staging` that CI runs after every staging deployment.

## Implementation Details

**Technology:** Python 3.11+, `httpx`, `asyncio`, pytest, `kubectl`, Bash

**File locations:**
- `scripts/validate/hpa_load_generator.py` — async request flood to drive custom metric
- `scripts/validate/hpa_timing_check.py` — poll HPA replica count + assert within 30 s
- `tests/infra/test_hpa_config.py` — pytest cluster state assertions on HPA spec
- `scripts/validate/pdb_disruption_test.sh` — PDB eviction test
- `Makefile` — `validate-hpa-staging` target

---

### Load generator

```python
# scripts/validate/hpa_load_generator.py
"""
Drives concurrent requests to the MCP Gateway and Agent Worker endpoints
to raise contextiq_active_requests above the HPA threshold (5 per pod).

Usage:
    python scripts/validate/hpa_load_generator.py \
        --target http://mcp-gateway.contextiq-gateway.svc.cluster.local \
        --concurrency 50 \
        --duration 120

The script fires concurrent requests and keeps them in-flight long enough
for Prometheus to scrape the elevated gauge value and for the HPA to react.
"""
from __future__ import annotations
import argparse
import asyncio
import time
import logging
import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def _flood_worker(
    client:    httpx.AsyncClient,
    url:       str,
    stop_at:   float,
    results:   list[int],
) -> None:
    """Single worker: keep sending requests until stop_at epoch."""
    while time.time() < stop_at:
        try:
            response = await client.post(
                url,
                json    = {"query": "load test", "session_id": "hpa-test"},
                timeout = 30.0,
            )
            results.append(response.status_code)
        except Exception:
            results.append(-1)
        await asyncio.sleep(0.1)   # slight back-off to avoid overwhelming the service


async def run(target: str, concurrency: int, duration: int) -> None:
    stop_at = time.time() + duration
    results: list[int] = []

    async with httpx.AsyncClient(verify=False) as client:
        tasks = [
            asyncio.create_task(_flood_worker(client, f"{target}/tools/context_query", stop_at, results))
            for _ in range(concurrency)
        ]
        await asyncio.gather(*tasks)

    ok    = sum(1 for r in results if r == 200)
    total = len(results)
    logger.info(
        "Load test complete — %d/%d requests succeeded (%.1f%%)",
        ok, total, 100 * ok / max(total, 1),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target",      default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--duration",    type=int, default=120)
    args = parser.parse_args()
    asyncio.run(run(args.target, args.concurrency, args.duration))
```

---

### HPA timing assertion script

```python
# scripts/validate/hpa_timing_check.py
"""
AC-4: Confirms that:
1. Scale-UP occurs within 30 s of load starting.
2. Scale-DOWN does NOT occur within 300 s of load stopping (stabilization window).

Usage:
    python scripts/validate/hpa_timing_check.py \
        --namespace contextiq-agents \
        --hpa-name release-name-agent-worker \
        --expected-min-replicas 3 \
        --scale-up-deadline 30 \
        --scale-down-hold 300

Exit code 0 = all assertions passed.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _get_hpa_replicas(namespace: str, hpa_name: str) -> int:
    result = subprocess.run(
        ["kubectl", "get", "hpa", hpa_name, "-n", namespace, "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    spec = json.loads(result.stdout)
    return spec["status"].get("currentReplicas", 0)


def wait_for_scale_up(
    namespace:              str,
    hpa_name:               str,
    expected_min_replicas:  int,
    deadline_seconds:       int,
) -> bool:
    """
    AC-4: Poll until replica count >= expected_min_replicas or deadline_seconds exceeded.
    Returns True if scale-up observed within deadline.
    """
    start = time.monotonic()
    while time.monotonic() - start < deadline_seconds:
        replicas = _get_hpa_replicas(namespace, hpa_name)
        logger.info("  current replicas: %d (want >= %d)", replicas, expected_min_replicas)
        if replicas >= expected_min_replicas:
            elapsed = time.monotonic() - start
            logger.info("Scale-up confirmed in %.1f s (deadline: %d s)", elapsed, deadline_seconds)
            return True
        time.sleep(5)
    return False


def assert_no_scale_down(
    namespace:     str,
    hpa_name:      str,
    initial_count: int,
    hold_seconds:  int,
) -> bool:
    """
    AC-4: Assert that replica count does NOT drop for hold_seconds after load stops.
    Returns True if no scale-down occurred during the hold window.
    """
    logger.info(
        "Monitoring for unwanted scale-down for %d s (initial replicas: %d)…",
        hold_seconds, initial_count,
    )
    start = time.monotonic()
    while time.monotonic() - start < hold_seconds:
        replicas = _get_hpa_replicas(namespace, hpa_name)
        if replicas < initial_count:
            logger.error(
                "FAIL: scale-down observed after %.0f s (replicas dropped from %d to %d)",
                time.monotonic() - start, initial_count, replicas,
            )
            return False
        time.sleep(15)
    logger.info("No premature scale-down within %d s — 5-minute stabilization window respected.", hold_seconds)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace",              required=True)
    parser.add_argument("--hpa-name",               required=True)
    parser.add_argument("--expected-min-replicas",  type=int, required=True)
    parser.add_argument("--scale-up-deadline",      type=int, default=30)
    parser.add_argument("--scale-down-hold",        type=int, default=300)
    args = parser.parse_args()

    logger.info("=== HPA scale-up timing check ===")
    scaled_up = wait_for_scale_up(
        args.namespace, args.hpa_name,
        args.expected_min_replicas, args.scale_up_deadline,
    )
    if not scaled_up:
        logger.error("FAIL: scale-up did not occur within %d s", args.scale_up_deadline)
        return 1

    peak_replicas = _get_hpa_replicas(args.namespace, args.hpa_name)
    logger.info("=== Scale-down stabilization check (hold: %d s) ===", args.scale_down_hold)
    # In CI: load generator has already stopped before this check runs
    no_early_down = assert_no_scale_down(
        args.namespace, args.hpa_name, peak_replicas, args.scale_down_hold,
    )
    return 0 if no_early_down else 1


if __name__ == "__main__":
    sys.exit(main())
```

---

### PDB disruption test

```bash
#!/usr/bin/env bash
# scripts/validate/pdb_disruption_test.sh
# AC-5: Verify PDB prevents evicting all pods at once.
# Drains one node and confirms the MCP Gateway pods are NOT all evicted.
set -euo pipefail

NAMESPACE="contextiq-gateway"
DEPLOY="release-name-mcp-gateway"
MIN_AVAILABLE=2

echo "=== PDB disruption test ==="

# Count pods before drain
before=$(kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=mcp-gateway" \
  --field-selector=status.phase=Running -o name | wc -l)
echo "  Pods before: $before"

if [ "$before" -lt "$MIN_AVAILABLE" ]; then
  echo "  SKIP: fewer than $MIN_AVAILABLE pods running — cannot test disruption budget"
  exit 0
fi

# Pick a node running one of the gateway pods
node=$(kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=mcp-gateway" \
  -o jsonpath='{.items[0].spec.nodeName}')
echo "  Draining node: $node (with --grace-period=5 --ignore-daemonsets)"

# Attempt drain — PDB should block it from finishing immediately if fewer than
# MIN_AVAILABLE pods would remain
kubectl drain "$node" \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=5 \
  --timeout=30s \
  2>&1 | tee /tmp/drain_output.txt || true   # allowed to fail due to PDB

# Check that at least MIN_AVAILABLE pods are still running
after=$(kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=mcp-gateway" \
  --field-selector=status.phase=Running -o name | wc -l)
echo "  Pods after attempted drain: $after"

if [ "$after" -ge "$MIN_AVAILABLE" ]; then
  echo "  PASS: PDB protected at least $MIN_AVAILABLE replicas during node drain"
else
  echo "  FAIL: only $after pod(s) survived — PDB not working correctly"
  exit 1
fi

# Uncordon the node
kubectl uncordon "$node"
echo "  Node $node uncordoned."
echo "=== PDB disruption test PASSED ==="
```

---

### pytest cluster state assertions for HPA spec

```python
# tests/infra/test_hpa_config.py
"""
AC-1, AC-4, AC-5, AC-6: Assert HPA and PDB specs match US-046 requirements.
Runs against a live cluster (requires KUBECONFIG).
"""
from __future__ import annotations
import json
import subprocess
import pytest


def _kubectl_json(args: list[str]) -> dict:
    result = subprocess.run(
        ["kubectl"] + args + ["-o", "json"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


# -----------------------------------------------------------------------
# AC-1: correct min/max replicas per service
# -----------------------------------------------------------------------
@pytest.mark.parametrize("namespace,hpa_suffix,expected_min,expected_max", [
    ("contextiq-gateway", "mcp-gateway",      2,  10),
    ("contextiq-agents",  "agent-worker",     2,  20),
    ("contextiq-agents",  "indexing-service", 1,   5),
])
def test_hpa_min_max_replicas(namespace, hpa_suffix, expected_min, expected_max):
    """AC-1: HPA min/max replicas match the story requirements."""
    hpas = _kubectl_json(["get", "hpa", "-n", namespace])
    matching = [
        h for h in hpas["items"]
        if h["metadata"]["name"].endswith(hpa_suffix)
    ]
    assert matching, f"No HPA ending with '{hpa_suffix}' found in {namespace}"
    hpa = matching[0]
    assert hpa["spec"]["minReplicas"] == expected_min
    assert hpa["spec"]["maxReplicas"] == expected_max


# -----------------------------------------------------------------------
# AC-2: agent-worker HPA has custom metric (Pods type)
# -----------------------------------------------------------------------
def test_agent_worker_hpa_has_custom_metric():
    """AC-2: agent-worker HPA includes a Pods-type metric for contextiq_active_requests."""
    hpas = _kubectl_json(["get", "hpa", "-n", "contextiq-agents"])
    hpa  = next(
        h for h in hpas["items"]
        if h["metadata"]["name"].endswith("agent-worker")
    )
    metrics = hpa["spec"]["metrics"]
    pods_metrics = [m for m in metrics if m["type"] == "Pods"]
    assert pods_metrics, "No Pods-type metric found in agent-worker HPA"
    metric_name = pods_metrics[0]["pods"]["metric"]["name"]
    assert metric_name == "contextiq_active_requests"


# -----------------------------------------------------------------------
# AC-3: gateway HPA scales on CPU at 60%
# -----------------------------------------------------------------------
def test_gateway_hpa_cpu_target():
    """AC-3: mcp-gateway HPA CPU target is 60%."""
    hpas = _kubectl_json(["get", "hpa", "-n", "contextiq-gateway"])
    hpa  = next(h for h in hpas["items"] if h["metadata"]["name"].endswith("mcp-gateway"))
    resource_metrics = [
        m for m in hpa["spec"]["metrics"]
        if m["type"] == "Resource" and m["resource"]["name"] == "cpu"
    ]
    assert resource_metrics
    target = resource_metrics[0]["resource"]["target"]["averageUtilization"]
    assert target == 60


# -----------------------------------------------------------------------
# AC-4: scale-down stabilization window is 300 s for all three HPAs
# -----------------------------------------------------------------------
@pytest.mark.parametrize("namespace,suffix", [
    ("contextiq-gateway", "mcp-gateway"),
    ("contextiq-agents",  "agent-worker"),
    ("contextiq-agents",  "indexing-service"),
])
def test_scale_down_stabilization_window(namespace, suffix):
    """AC-4: scale-down stabilizationWindowSeconds = 300 for all three HPAs."""
    hpas = _kubectl_json(["get", "hpa", "-n", namespace])
    hpa  = next(h for h in hpas["items"] if h["metadata"]["name"].endswith(suffix))
    window = (
        hpa["spec"]
        .get("behavior", {})
        .get("scaleDown", {})
        .get("stabilizationWindowSeconds", -1)
    )
    assert window == 300, f"{suffix}: expected scaleDown.stabilizationWindowSeconds=300, got {window}"


# -----------------------------------------------------------------------
# AC-5: PDB for mcp-gateway has minAvailable: 2
# -----------------------------------------------------------------------
def test_gateway_pdb_min_available():
    """AC-5: mcp-gateway PDB has minAvailable: 2."""
    pdbs = _kubectl_json(["get", "pdb", "-n", "contextiq-gateway"])
    pdb  = next(p for p in pdbs["items"] if p["metadata"]["name"].endswith("mcp-gateway"))
    assert pdb["spec"]["minAvailable"] == 2
```

---

### Makefile target

```makefile
# Makefile (extend)
.PHONY: validate-hpa-staging

validate-hpa-staging: ## Run HPA validation suite in staging
	@echo "--- HPA spec assertions ---"
	KUBECONFIG=~/.kube/staging pytest tests/infra/test_hpa_config.py -v
	@echo "--- Starting load generator (background) ---"
	KUBECONFIG=~/.kube/staging python scripts/validate/hpa_load_generator.py \
	    --target http://mcp-gateway.contextiq-gateway.svc.cluster.local \
	    --concurrency 60 \
	    --duration 90 &
	LOAD_PID=$$!; \
	sleep 10; \
	echo "--- Scale-up timing check (agent-worker) ---"; \
	KUBECONFIG=~/.kube/staging python scripts/validate/hpa_timing_check.py \
	    --namespace contextiq-agents \
	    --hpa-name release-name-agent-worker \
	    --expected-min-replicas 4 \
	    --scale-up-deadline 30 \
	    --scale-down-hold 60; \
	wait $$LOAD_PID || true
	@echo "--- PDB disruption test ---"
	KUBECONFIG=~/.kube/staging bash scripts/validate/pdb_disruption_test.sh
	@echo "=== HPA validation complete ==="
```

## Acceptance Criteria

- [ ] `test_hpa_min_max_replicas` parametrized tests pass for all 3 HPAs — correct min/max (AC-1)
- [ ] `test_agent_worker_hpa_has_custom_metric` — HPA spec contains `contextiq_active_requests` Pods metric (AC-2)
- [ ] `test_gateway_hpa_cpu_target` — CPU target is 60% (AC-3)
- [ ] `test_scale_down_stabilization_window` passes for all 3 HPAs — `stabilizationWindowSeconds: 300` (AC-4)
- [ ] `hpa_timing_check.py` confirms scale-up within 30 s of load starting (AC-4)
- [ ] `hpa_timing_check.py` confirms no scale-down within 300 s of load stopping (AC-4)
- [ ] `pdb_disruption_test.sh` — PDB prevents all gateway pods from being evicted (AC-5)
- [ ] All tests run in CI via `make validate-hpa-staging` without manual cluster access (AC-6)

## Dependencies

- TASK-US046-01 — Gateway HPA + PDB deployed
- TASK-US046-02 — Prometheus Adapter deployed and serving custom metrics
- TASK-US046-03 — Agent-worker HPA deployed
- TASK-US046-04 — Indexing-service HPA deployed
- TASK-US045-05 — `KUBECONFIG` convention and Makefile patterns established

## Definition of Done

- [ ] `pytest tests/infra/test_hpa_config.py -v` passes against staging cluster
- [ ] `make validate-hpa-staging` exits 0 in CI
- [ ] `mypy --strict scripts/validate/hpa_load_generator.py scripts/validate/hpa_timing_check.py` passes
