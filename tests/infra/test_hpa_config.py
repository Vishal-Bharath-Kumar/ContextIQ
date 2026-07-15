"""
AC-1, AC-2, AC-3, AC-4, AC-5: Assert HPA and PDB specs match US-046 requirements.
Runs against a live cluster (requires KUBECONFIG set in the environment).

Run:
    KUBECONFIG=~/.kube/staging pytest tests/infra/test_hpa_config.py -v
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest


def _kubectl_json(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def _find_hpa(namespace: str, suffix: str) -> dict[str, Any]:
    """Return the first HPA whose name ends with *suffix*, or raise AssertionError."""
    hpas = _kubectl_json(["get", "hpa", "-n", namespace])
    items: list[dict[str, Any]] = hpas.get("items", [])
    match = next((h for h in items if h["metadata"]["name"].endswith(suffix)), None)
    assert match is not None, f"No HPA ending with '{suffix}' found in namespace '{namespace}'"
    return match


# -----------------------------------------------------------------------
# AC-1: correct min/max replicas per service
# -----------------------------------------------------------------------
@pytest.mark.parametrize("namespace,hpa_suffix,expected_min,expected_max", [
    ("contextiq-gateway", "mcp-gateway",      2,  10),
    ("contextiq-agents",  "agent-worker",     2,  20),
    ("contextiq-agents",  "indexing-service", 1,   5),
])
def test_hpa_min_max_replicas(
    namespace: str, hpa_suffix: str, expected_min: int, expected_max: int,
) -> None:
    """AC-1: HPA min/max replicas match the story requirements."""
    hpa = _find_hpa(namespace, hpa_suffix)
    spec: dict[str, Any] = hpa["spec"]
    assert spec["minReplicas"] == expected_min, (
        f"{hpa_suffix}: expected minReplicas={expected_min}, got {spec['minReplicas']}"
    )
    assert spec["maxReplicas"] == expected_max, (
        f"{hpa_suffix}: expected maxReplicas={expected_max}, got {spec['maxReplicas']}"
    )


# -----------------------------------------------------------------------
# AC-2: agent-worker HPA has custom Pods metric for contextiq_active_requests
# -----------------------------------------------------------------------
def test_agent_worker_hpa_has_custom_metric() -> None:
    """AC-2: agent-worker HPA contains a Pods-type metric for contextiq_active_requests."""
    hpa = _find_hpa("contextiq-agents", "agent-worker")
    metrics: list[dict[str, Any]] = hpa["spec"].get("metrics", [])
    pods_metrics = [m for m in metrics if m.get("type") == "Pods"]
    assert pods_metrics, "No Pods-type metric found in agent-worker HPA (AC-2)"
    metric_name: str = pods_metrics[0]["pods"]["metric"]["name"]
    assert metric_name == "contextiq_active_requests", (
        f"Expected contextiq_active_requests, got {metric_name!r} (AC-2)"
    )


# -----------------------------------------------------------------------
# AC-3: mcp-gateway HPA CPU target is 60%
# -----------------------------------------------------------------------
def test_gateway_hpa_cpu_target() -> None:
    """AC-3: mcp-gateway HPA CPU averageUtilization target is 60%."""
    hpa = _find_hpa("contextiq-gateway", "mcp-gateway")
    metrics: list[dict[str, Any]] = hpa["spec"].get("metrics", [])
    resource_metrics = [
        m for m in metrics
        if m.get("type") == "Resource" and m.get("resource", {}).get("name") == "cpu"
    ]
    assert resource_metrics, "No CPU Resource metric found in mcp-gateway HPA (AC-3)"
    target: int = resource_metrics[0]["resource"]["target"]["averageUtilization"]
    assert target == 60, f"Expected CPU target 60%, got {target}% (AC-3)"


# -----------------------------------------------------------------------
# AC-4: scale-down stabilizationWindowSeconds == 300 for all three HPAs
# -----------------------------------------------------------------------
@pytest.mark.parametrize("namespace,suffix", [
    ("contextiq-gateway", "mcp-gateway"),
    ("contextiq-agents",  "agent-worker"),
    ("contextiq-agents",  "indexing-service"),
])
def test_scale_down_stabilization_window(namespace: str, suffix: str) -> None:
    """AC-4: scale-down stabilizationWindowSeconds = 300 for all three HPAs."""
    hpa = _find_hpa(namespace, suffix)
    window: int = (
        hpa["spec"]
        .get("behavior", {})
        .get("scaleDown", {})
        .get("stabilizationWindowSeconds", -1)
    )
    assert window == 300, (
        f"{suffix}: expected scaleDown.stabilizationWindowSeconds=300, got {window} (AC-4)"
    )


# -----------------------------------------------------------------------
# AC-5: PDB for mcp-gateway has minAvailable: 2
# -----------------------------------------------------------------------
def test_gateway_pdb_min_available() -> None:
    """AC-5: mcp-gateway PDB enforces minAvailable: 2."""
    pdbs = _kubectl_json(["get", "pdb", "-n", "contextiq-gateway"])
    items: list[dict[str, Any]] = pdbs.get("items", [])
    pdb = next(
        (p for p in items if p["metadata"]["name"].endswith("mcp-gateway")),
        None,
    )
    assert pdb is not None, "No PDB ending with 'mcp-gateway' found in contextiq-gateway (AC-5)"
    min_available: int = pdb["spec"]["minAvailable"]
    assert min_available == 2, f"Expected minAvailable=2, got {min_available} (AC-5)"
