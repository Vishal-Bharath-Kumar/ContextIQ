"""
Structured assertions on cluster state after deployment.
Requires KUBECONFIG environment variable pointing to the target cluster.

Run with:
    pytest tests/infra/ -v --timeout=120
"""
from __future__ import annotations

import json
import subprocess

import pytest

NAMESPACES: list[str] = [
    "contextiq-data",
    "contextiq-agents",
    "contextiq-gateway",
    "contextiq-admin",
    "contextiq-observability",
    "contextiq-security",
    "contextiq-infra",
]


def _kubectl(args: list[str]) -> dict:  # type: ignore[type-arg]
    """Run a kubectl command and return parsed JSON output."""
    result = subprocess.run(
        ["kubectl"] + args + ["-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


class TestNamespaces:
    """AC-1: All 7 canonical namespaces exist."""

    def test_all_namespaces_exist(self) -> None:
        ns_list = _kubectl(["get", "namespaces"])
        existing = {ns["metadata"]["name"] for ns in ns_list["items"]}
        for ns in NAMESPACES:
            assert ns in existing, f"Namespace {ns} does not exist"


class TestResourceQuotas:
    """AC-3: Every namespace has exactly one ResourceQuota named 'quota'."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_quota_exists(self, namespace: str) -> None:
        quota = _kubectl(["get", "resourcequota", "quota", "-n", namespace])
        assert quota["metadata"]["name"] == "quota"
        assert int(quota["status"]["hard"].get("pods", "0")) > 0


class TestLimitRanges:
    """AC-3: Every namespace has a LimitRange named 'default-limits' with a Container entry."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_limitrange_exists(self, namespace: str) -> None:
        lr = _kubectl(["get", "limitrange", "default-limits", "-n", namespace])
        limits = lr["spec"]["limits"]
        container_limits = [lim for lim in limits if lim["type"] == "Container"]
        assert len(container_limits) == 1, (
            f"{namespace}: expected 1 Container LimitRange entry, got {len(container_limits)}"
        )


class TestNetworkPolicies:
    """AC-4: Every namespace has the default-deny-all NetworkPolicy with no allow rules."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_default_deny_policy_exists(self, namespace: str) -> None:
        np = _kubectl(["get", "networkpolicy", "default-deny-all", "-n", namespace])
        assert np["spec"]["podSelector"] == {}, (
            f"{namespace}: podSelector must be empty (match all pods)"
        )
        assert "Ingress" in np["spec"]["policyTypes"], (
            f"{namespace}: policyTypes must include Ingress"
        )
        assert "Egress" in np["spec"]["policyTypes"], (
            f"{namespace}: policyTypes must include Egress"
        )
        # A deny-all policy has no ingress or egress rule entries
        assert "ingress" not in np["spec"], (
            f"{namespace}: default-deny must not contain ingress rules"
        )
        assert "egress" not in np["spec"], (
            f"{namespace}: default-deny must not contain egress rules"
        )


class TestDeploymentReadiness:
    """AC-5: All Deployments in contextiq-* namespaces are fully available."""

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_all_deployments_available(self, namespace: str) -> None:
        deploys = _kubectl(["get", "deployments", "-n", namespace])
        for deploy in deploys.get("items", []):
            name = deploy["metadata"]["name"]
            desired = deploy["spec"].get("replicas", 1)
            available = deploy["status"].get("availableReplicas", 0)
            assert available >= desired, (
                f"{namespace}/{name}: desired={desired}, available={available}"
            )
