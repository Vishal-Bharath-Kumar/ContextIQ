"""
Integration tests for US-047: HashiCorp Vault secrets management.
Covers all 7 acceptance criteria.

Run non-destructive tests (safe for shared clusters):
    pytest tests/security/test_vault_integration.py -v --tb=short

Run full suite including HA failover (staging only):
    pytest tests/security/test_vault_integration.py -v --tb=short --run-destructive
"""
from __future__ import annotations

import json
import subprocess
import time

import hvac
import pytest
from kubernetes import client as k8s_client
from kubernetes import client as _k8s


class TestAC1VaultHADeployment:
    """AC-1 — 3-node Vault HA Raft cluster, auto-unseal, PDB enforced."""

    def test_three_vault_pods_running(self, k8s: k8s_client.CoreV1Api) -> None:
        pods = k8s.list_namespaced_pod(
            namespace="contextiq-security",
            label_selector="app.kubernetes.io/name=vault,component=server",
        )
        running = [p for p in pods.items if p.status.phase == "Running"]
        assert len(running) == 3, f"Expected 3 Vault server pods, found {len(running)}"

    def test_vault_not_sealed(self, vault_client: hvac.Client) -> None:
        status = vault_client.sys.read_health_status(method="GET")
        assert not status["sealed"], "Vault is sealed — auto-unseal failed"

    def test_vault_ha_enabled(self, vault_client: hvac.Client) -> None:
        status = vault_client.sys.read_health_status(method="GET")
        ha_active = status.get("ha_enabled") is True or status.get("performance_standby") is not None
        assert ha_active, "Vault HA mode does not appear to be enabled"

    def test_pdb_min_available_2(self, k8s: k8s_client.CoreV1Api) -> None:
        policy_api = _k8s.PolicyV1Api()
        pdbs = policy_api.list_namespaced_pod_disruption_budget(namespace="contextiq-security")
        vault_pdb = next((p for p in pdbs.items if "vault" in p.metadata.name), None)
        assert vault_pdb is not None, "No PodDisruptionBudget found for Vault in contextiq-security"
        assert vault_pdb.spec.min_available == 2, (
            f"Expected minAvailable=2, got {vault_pdb.spec.min_available}"
        )


class TestAC2DatabaseSecretsEngines:
    """AC-2 — All four secrets engines mounted; dynamic credential issuance works."""

    @pytest.mark.parametrize("mount_path", [
        "database/postgres",
        "database/redis",
        "database/neo4j",
        "secret",
    ])
    def test_secrets_engine_mounted(self, vault_client: hvac.Client, mount_path: str) -> None:
        mounts = vault_client.sys.list_mounted_secrets_engines()
        assert f"{mount_path}/" in mounts["data"], (
            f"Secrets engine not mounted at {mount_path}/"
        )

    def test_postgres_dynamic_credentials_unique(self, vault_client: hvac.Client) -> None:
        cred_1 = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        cred_2 = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        assert cred_1["data"]["username"] != cred_2["data"]["username"], (
            "Two consecutive credential requests returned the same username — credentials are not dynamic"
        )


class TestAC3VaultAgentInjection:
    """AC-3 — Vault Agent sidecar present in running pods; /vault/secrets/ populated."""

    @pytest.mark.parametrize("namespace,label", [
        ("contextiq-gateway", "app.kubernetes.io/name=mcp-gateway"),
        ("contextiq-agents",  "app.kubernetes.io/name=agent-worker"),
    ])
    def test_vault_agent_sidecar_present(
        self,
        k8s: k8s_client.CoreV1Api,
        namespace: str,
        label: str,
    ) -> None:
        pods = k8s.list_namespaced_pod(namespace=namespace, label_selector=label)
        assert pods.items, f"No pods found for {label} in {namespace}"
        pod = pods.items[0]
        container_names = [c.name for c in pod.spec.containers]
        assert "vault-agent" in container_names, (
            f"vault-agent sidecar missing from pod {pod.metadata.name}; "
            f"containers present: {container_names}"
        )

    def test_vault_secrets_file_present_in_gateway(self, k8s: k8s_client.CoreV1Api) -> None:
        pods = k8s.list_namespaced_pod(
            namespace="contextiq-gateway",
            label_selector="app.kubernetes.io/name=mcp-gateway",
        )
        assert pods.items, "No mcp-gateway pods found in contextiq-gateway"
        pod_name = pods.items[0].metadata.name
        result = subprocess.run(
            ["kubectl", "exec", "-n", "contextiq-gateway", pod_name, "--",
             "test", "-f", "/vault/secrets/postgres.env"],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"/vault/secrets/postgres.env not found in pod {pod_name}"
        )


class TestAC4DynamicCredentialTTL:
    """AC-4 — Dynamic credentials have ~1h TTL; lease is renewable (agent renews before expiry)."""

    def test_postgres_credential_ttl_is_one_hour(self, vault_client: hvac.Client) -> None:
        response = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        lease_duration: int = response["lease_duration"]
        # 1h = 3600s; allow ±10s tolerance for clock skew
        assert 3590 <= lease_duration <= 3600, (
            f"Expected ~3600s TTL, got {lease_duration}s"
        )

    def test_lease_is_renewable(self, vault_client: hvac.Client) -> None:
        response = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        assert response["renewable"] is True, (
            f"Lease {response['lease_id']} is not renewable — Vault Agent sidecar cannot renew it"
        )


class TestAC5NoRemainingStaticSecrets:
    """AC-5 — All static DB secrets migrated; no raw passwords remain in Kubernetes Secrets."""

    EXPECTED_MIGRATED_SECRETS = [
        ("contextiq-data",     "postgres-admin-credentials"),
        ("contextiq-data",     "redis-credentials"),
        ("contextiq-security", "keycloak-admin-credentials"),
        ("contextiq-security", "entra-id-oidc-credentials"),
    ]

    @pytest.mark.parametrize("namespace,secret_name", EXPECTED_MIGRATED_SECRETS)
    def test_static_secret_annotated_migrated_or_deleted(
        self,
        k8s: k8s_client.CoreV1Api,
        namespace: str,
        secret_name: str,
    ) -> None:
        try:
            secret = k8s.read_namespaced_secret(name=secret_name, namespace=namespace)
        except _k8s.exceptions.ApiException as exc:
            if exc.status == 404:
                # Secret deleted after migration — this is the ideal final state
                return
            raise
        annotations = secret.metadata.annotations or {}
        assert annotations.get("vault.hashicorp.com/migrated") == "true", (
            f"Secret {namespace}/{secret_name} exists and is NOT annotated as migrated — "
            "static credentials may still be in use"
        )


class TestAC6AuditLog:
    """AC-6 — Vault audit log enabled; entries appear in audit output; log_raw=false."""

    def test_audit_file_device_enabled(self, vault_client: hvac.Client) -> None:
        devices = vault_client.sys.list_enabled_audit_devices()
        assert "file/" in devices["data"], "File audit device not enabled in Vault"

    def test_audit_syslog_device_enabled(self, vault_client: hvac.Client) -> None:
        devices = vault_client.sys.list_enabled_audit_devices()
        assert "syslog/" in devices["data"], "Syslog audit device not enabled in Vault"

    def test_audit_device_not_logging_raw(self, vault_client: hvac.Client) -> None:
        """OWASP A02: plaintext secret values must never appear in audit logs."""
        devices = vault_client.sys.list_enabled_audit_devices()
        options = devices["data"]["file/"]["options"]
        assert options.get("log_raw", "false") == "false", (
            "SECURITY VIOLATION: Vault audit device has log_raw=true — "
            "plaintext secrets may be written to the audit log"
        )


class TestAC7HAFailover:
    """
    AC-7 — Primary node failure triggers leader re-election within 30 seconds.

    DESTRUCTIVE: This test force-deletes a Vault pod.
    Only run in dedicated staging environments.
    Requires: --run-destructive pytest flag.
    """

    @pytest.mark.destructive
    def test_leader_re_elected_within_30_seconds(
        self,
        vault_client: hvac.Client,
        k8s: k8s_client.CoreV1Api,
    ) -> None:
        NAMESPACE = "contextiq-security"
        MAX_RECOVERY_SECONDS = 30

        # Identify current leader
        pods = k8s.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector="app.kubernetes.io/name=vault,component=server",
        )
        leader_pod: str | None = None
        for pod in pods.items:
            try:
                result = subprocess.run(
                    ["kubectl", "exec", "-n", NAMESPACE, pod.metadata.name, "--",
                     "vault", "status", "-format=json"],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    status = json.loads(result.stdout)
                    if not status.get("sealed") and status.get("is_self"):
                        leader_pod = pod.metadata.name
                        break
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                continue

        assert leader_pod is not None, "Could not identify Vault leader pod before failover test"

        # Force-delete the leader pod to trigger Raft leader election
        start = time.monotonic()
        k8s.delete_namespaced_pod(
            name=leader_pod,
            namespace=NAMESPACE,
            grace_period_seconds=0,
        )

        # Poll the remaining pods until a new active leader is found
        while time.monotonic() - start < MAX_RECOVERY_SECONDS:
            time.sleep(2)
            for pod in pods.items:
                if pod.metadata.name == leader_pod:
                    continue   # skip the deleted pod
                try:
                    result = subprocess.run(
                        ["kubectl", "exec", "-n", NAMESPACE, pod.metadata.name, "--",
                         "vault", "status", "-format=json"],
                        capture_output=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        status = json.loads(result.stdout)
                        if not status.get("sealed") and status.get("is_self"):
                            elapsed = time.monotonic() - start
                            assert elapsed < MAX_RECOVERY_SECONDS, (
                                f"Leader re-elected but took {elapsed:.1f}s > {MAX_RECOVERY_SECONDS}s limit"
                            )
                            return   # test passed
                except (subprocess.TimeoutExpired, json.JSONDecodeError, _k8s.exceptions.ApiException):
                    continue

        pytest.fail(
            f"No new Vault leader elected within {MAX_RECOVERY_SECONDS}s "
            f"after deleting leader pod {leader_pod}"
        )
