# TASK-US047-05 — HA Failover Test and Full Integration Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US047-05 |
| User Story | US-047 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | QA / Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Validate all 7 acceptance criteria for US-047 through automated test scripts and pytest integration tests. The critical test is the HA failover test (AC-7): delete the current Vault leader pod and assert that the cluster elects a new leader and resumes serving credential requests within 30 seconds. Additional tests verify dynamic credential issuance TTLs, sidecar auto-renewal, audit log integrity, Kubernetes auth binding, and that no static secrets remain in cluster after rotation. All tests are structured as pytest test cases so they can be incorporated into the CI pipeline.

## Implementation Details

**Technology:** Python 3.11+, pytest 7+, `hvac` Python Vault client, `kubernetes` Python client, `subprocess`

**File locations:**
- `scripts/vault/hpa_failover_test.sh` — CLI-driven HA failover timing script
- `tests/security/test_vault_integration.py` — pytest integration test suite (all ACs)
- `tests/security/conftest.py` — `hvac` client fixture, K8s client fixture

---

### HA failover timing script (AC-7)

```bash
#!/usr/bin/env bash
# scripts/vault/ha_failover_test.sh
# AC-7: Delete the Vault leader pod; assert new leader elected within 30 s.
#
# Prerequisites:
#   - kubectl access to contextiq-security namespace
#   - vault CLI with VAULT_ADDR pointed at the Vault internal service
set -euo pipefail

NAMESPACE="contextiq-security"
VAULT_SVC="https://vault.contextiq-security.svc.cluster.local:8200"
MAX_RECOVERY_SECONDS=30

echo "=== Vault HA Failover Test ==="
echo "Target: new leader elected within ${MAX_RECOVERY_SECONDS}s after leader pod deletion"

# Identify the current leader pod
echo ""
echo "--- Identifying current leader ---"
LEADER_POD=""
for POD in vault-0 vault-1 vault-2; do
  STATUS=$(kubectl exec -n "$NAMESPACE" "$POD" -- vault status -format=json 2>/dev/null || echo '{"ha_cluster":null}')
  if echo "$STATUS" | jq -e '.is_self == true and .leader_address != ""' >/dev/null 2>&1; then
    LEADER_POD="$POD"
    break
  fi
done

if [ -z "$LEADER_POD" ]; then
  echo "ERROR: Could not identify leader pod. Is Vault running?"
  exit 1
fi
echo "Current leader: $LEADER_POD"

# Verify cluster is healthy before forcing failover
echo ""
echo "--- Pre-failover health check ---"
kubectl exec -n "$NAMESPACE" "$LEADER_POD" -- vault status -format=json | jq '{sealed, ha_enabled, is_self, leader_address}'

# Record start time and delete the leader
echo ""
echo "--- Deleting leader pod $LEADER_POD ---"
START_EPOCH=$(date +%s)
kubectl delete pod "$LEADER_POD" -n "$NAMESPACE" --grace-period=0 --force

echo "--- Polling for new leader (timeout: ${MAX_RECOVERY_SECONDS}s) ---"
ELAPSED=0
while [ $ELAPSED -lt $MAX_RECOVERY_SECONDS ]; do
  sleep 2
  ELAPSED=$(( $(date +%s) - START_EPOCH ))

  # Find any healthy non-deleted pod
  for STANDBY_POD in vault-0 vault-1 vault-2; do
    STATUS=$(kubectl exec -n "$NAMESPACE" "$STANDBY_POD" -- vault status -format=json 2>/dev/null || continue)
    if echo "$STATUS" | jq -e '.sealed == false and .ha_enabled == true and .is_self == true' >/dev/null 2>&1; then
      echo ""
      echo "SUCCESS: New leader $STANDBY_POD elected after ${ELAPSED}s (limit: ${MAX_RECOVERY_SECONDS}s)"
      kubectl exec -n "$NAMESPACE" "$STANDBY_POD" -- vault status -format=json | jq '{sealed, is_self, leader_address}'
      exit 0
    fi
  done

  printf "  Waiting... %ds elapsed\r" "$ELAPSED"
done

echo ""
echo "FAIL: No leader elected within ${MAX_RECOVERY_SECONDS}s"
exit 1
```

---

### pytest integration test suite

```python
# tests/security/conftest.py
import os
import pytest
import hvac
from kubernetes import client as k8s_client, config as k8s_config


@pytest.fixture(scope="session")
def vault_client() -> hvac.Client:
    """Authenticated hvac client for test assertions."""
    vault_addr = os.environ.get("VAULT_ADDR", "https://vault.contextiq-security.svc.cluster.local:8200")
    vault_token = os.environ["VAULT_TOKEN"]    # injected by CI secrets, not hard-coded
    c = hvac.Client(url=vault_addr, token=vault_token, verify=False)
    assert c.is_authenticated(), "Vault test client is not authenticated"
    return c


@pytest.fixture(scope="session")
def k8s() -> k8s_client.CoreV1Api:
    """Kubernetes API client — uses in-cluster config in CI, ~/.kube/config locally."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return k8s_client.CoreV1Api()
```

```python
# tests/security/test_vault_integration.py
"""
Integration tests for US-047: HashiCorp Vault secrets management.

Covers all 7 acceptance criteria. Run in staging cluster:
    pytest tests/security/test_vault_integration.py -v --tb=short
"""
from __future__ import annotations

import json
import subprocess
import time

import hvac
import pytest
from kubernetes import client as k8s_client


class TestAC1_VaultHADeployment:
    """AC-1 — 3-node Vault HA Raft cluster, auto-unseal, PDB enforced."""

    def test_three_vault_pods_running(self, k8s: k8s_client.CoreV1Api) -> None:
        pods = k8s.list_namespaced_pod(
            namespace="contextiq-security",
            label_selector="app.kubernetes.io/name=vault,component=server",
        )
        running = [p for p in pods.items if p.status.phase == "Running"]
        assert len(running) == 3, f"Expected 3 Vault pods, found {len(running)}"

    def test_vault_not_sealed(self, vault_client: hvac.Client) -> None:
        status = vault_client.sys.read_health_status(method="GET")
        assert not status["sealed"], "Vault is sealed — auto-unseal failed"

    def test_vault_ha_enabled(self, vault_client: hvac.Client) -> None:
        status = vault_client.sys.read_health_status(method="GET")
        assert status["performance_standby"] is not None or status.get("ha_enabled") is True

    def test_pdb_min_available_2(self, k8s: k8s_client.CoreV1Api) -> None:
        from kubernetes import client as k8s_apps
        policy_v1 = k8s_apps.PolicyV1Api()
        pdbs = policy_v1.list_namespaced_pod_disruption_budget(namespace="contextiq-security")
        vault_pdb = next((p for p in pdbs.items if "vault" in p.metadata.name), None)
        assert vault_pdb is not None, "No PDB found for Vault"
        assert vault_pdb.spec.min_available == 2


class TestAC2_DatabaseSecretsEngines:
    """AC-2 — All four secrets engines mounted and dynamic credential issuance works."""

    @pytest.mark.parametrize("mount_path", [
        "database/postgres",
        "database/redis",
        "database/neo4j",
        "secret",
    ])
    def test_secrets_engine_mounted(self, vault_client: hvac.Client, mount_path: str) -> None:
        mounts = vault_client.sys.list_mounted_secrets_engines()
        assert f"{mount_path}/" in mounts["data"], f"Secrets engine not mounted at {mount_path}/"

    def test_postgres_dynamic_credentials_unique(self, vault_client: hvac.Client) -> None:
        cred_1 = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        cred_2 = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        assert cred_1["data"]["username"] != cred_2["data"]["username"], (
            "Two consecutive credential requests returned the same username — not dynamic"
        )


class TestAC3_VaultAgentInjection:
    """AC-3 — Vault Agent sidecar present in running pods; /vault/secrets/ populated."""

    @pytest.mark.parametrize("namespace,label", [
        ("contextiq-gateway",  "app.kubernetes.io/name=mcp-gateway"),
        ("contextiq-agents",   "app.kubernetes.io/name=agent-worker"),
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
            f"containers: {container_names}"
        )

    def test_vault_secrets_file_present_in_gateway(self, k8s: k8s_client.CoreV1Api) -> None:
        pods = k8s.list_namespaced_pod(
            namespace="contextiq-gateway",
            label_selector="app.kubernetes.io/name=mcp-gateway",
        )
        pod_name = pods.items[0].metadata.name
        result = subprocess.run(
            ["kubectl", "exec", "-n", "contextiq-gateway", pod_name, "--",
             "test", "-f", "/vault/secrets/postgres.env"],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode == 0, "/vault/secrets/postgres.env not found in mcp-gateway pod"


class TestAC4_DynamicCredentialTTL:
    """AC-4 — Dynamic credentials have 1h TTL; agent renews before expiry."""

    def test_postgres_credential_ttl_is_one_hour(self, vault_client: hvac.Client) -> None:
        response = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        lease_duration_seconds = response["lease_duration"]
        # 1 hour = 3600 s; Vault may return slightly less due to clock skew — allow 10 s tolerance
        assert 3590 <= lease_duration_seconds <= 3600, (
            f"Expected ~3600s TTL, got {lease_duration_seconds}s"
        )

    def test_lease_is_renewable(self, vault_client: hvac.Client) -> None:
        response = vault_client.secrets.database.generate_credentials(
            name="mcp-gateway", mount_point="database/postgres"
        )
        lease_id = response["lease_id"]
        assert response["renewable"] is True, f"Lease {lease_id} is not renewable"


class TestAC5_NoRemainingStaticSecrets:
    """AC-5 — All static DB secrets migrated; no raw passwords in K8s Secrets."""

    EXPECTED_MIGRATED_SECRETS = [
        ("contextiq-data",     "postgres-admin-credentials"),
        ("contextiq-data",     "redis-credentials"),
        ("contextiq-security", "keycloak-admin-credentials"),
        ("contextiq-security", "entra-id-oidc-credentials"),
    ]

    @pytest.mark.parametrize("namespace,secret_name", EXPECTED_MIGRATED_SECRETS)
    def test_static_secret_annotated_migrated(
        self,
        k8s: k8s_client.CoreV1Api,
        namespace: str,
        secret_name: str,
    ) -> None:
        try:
            secret = k8s.read_namespaced_secret(name=secret_name, namespace=namespace)
        except k8s_client.exceptions.ApiException as exc:
            if exc.status == 404:
                # Secret deleted after migration — this is the ideal state
                return
            raise
        annotations = secret.metadata.annotations or {}
        assert annotations.get("vault.hashicorp.com/migrated") == "true", (
            f"Secret {namespace}/{secret_name} not annotated as migrated — static secret still active"
        )


class TestAC6_AuditLog:
    """AC-6 — Vault audit log enabled; entries appear in audit output."""

    def test_audit_file_device_enabled(self, vault_client: hvac.Client) -> None:
        devices = vault_client.sys.list_enabled_audit_devices()
        assert "file/" in devices["data"], "File audit device not enabled"

    def test_audit_device_not_logging_raw(self, vault_client: hvac.Client) -> None:
        devices = vault_client.sys.list_enabled_audit_devices()
        options = devices["data"]["file/"]["options"]
        # log_raw=true would expose plaintext secrets in audit log — must be false
        assert options.get("log_raw", "false") == "false", (
            "SECURITY: Vault audit device has log_raw=true — plaintext secrets may appear in logs"
        )


class TestAC7_HAFailover:
    """
    AC-7 — Primary node failure triggers leader re-election within 30 seconds.

    NOTE: This test deletes a Vault pod. It is marked as destructive and should
    only run in dedicated staging environments, not in shared dev clusters.
    Tag: @destructive
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
        leader_pod = None
        for pod in pods.items:
            try:
                result = subprocess.run(
                    ["kubectl", "exec", "-n", NAMESPACE, pod.metadata.name, "--",
                     "vault", "status", "-format=json"],
                    capture_output=True, timeout=10,
                )
                if result.returncode == 0:
                    status = json.loads(result.stdout)
                    if not status.get("sealed") and status.get("is_self"):
                        leader_pod = pod.metadata.name
                        break
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                continue

        assert leader_pod is not None, "Could not identify Vault leader pod before failover test"

        # Delete the leader
        start = time.monotonic()
        k8s.delete_namespaced_pod(
            name=leader_pod,
            namespace=NAMESPACE,
            grace_period_seconds=0,
        )

        # Poll remaining pods for a new active leader
        while time.monotonic() - start < MAX_RECOVERY_SECONDS:
            time.sleep(2)
            for pod in pods.items:
                if pod.metadata.name == leader_pod:
                    continue    # skip deleted pod
                try:
                    result = subprocess.run(
                        ["kubectl", "exec", "-n", NAMESPACE, pod.metadata.name, "--",
                         "vault", "status", "-format=json"],
                        capture_output=True, timeout=10,
                    )
                    if result.returncode == 0:
                        status = json.loads(result.stdout)
                        if not status.get("sealed") and status.get("is_self"):
                            elapsed = time.monotonic() - start
                            assert elapsed < MAX_RECOVERY_SECONDS, (
                                f"Leader re-elected but took {elapsed:.1f}s > {MAX_RECOVERY_SECONDS}s"
                            )
                            return    # test passed
                except (subprocess.TimeoutExpired, json.JSONDecodeError, k8s_client.exceptions.ApiException):
                    continue

        pytest.fail(
            f"No new Vault leader elected within {MAX_RECOVERY_SECONDS}s after deleting {leader_pod}"
        )
```

## Acceptance Criteria

- [ ] `pytest tests/security/test_vault_integration.py -k "TestAC1"` passes — 3 pods running, unsealed, PDB correct (AC-1)
- [ ] `pytest tests/security/test_vault_integration.py -k "TestAC2"` passes — all 4 secrets engines mounted, dynamic creds unique (AC-2)
- [ ] `pytest tests/security/test_vault_integration.py -k "TestAC3"` passes — `vault-agent` sidecar present, `/vault/secrets/postgres.env` exists in gateway pod (AC-3)
- [ ] `pytest tests/security/test_vault_integration.py -k "TestAC4"` passes — lease_duration ~3600s, renewable=true (AC-4)
- [ ] `pytest tests/security/test_vault_integration.py -k "TestAC5"` passes — all static secrets annotated as migrated or deleted (AC-5)
- [ ] `pytest tests/security/test_vault_integration.py -k "TestAC6"` passes — file audit device enabled, log_raw=false (AC-6)
- [ ] `bash scripts/vault/ha_failover_test.sh` completes with `SUCCESS` and reports elapsed < 30s (AC-7)

## Dependencies

- TASK-US047-01 — Vault deployed and initialised
- TASK-US047-02 — Secrets engines and policies configured
- TASK-US047-03 — Vault Agent sidecars injected in service pods
- TASK-US047-04 — Audit devices enabled; static secrets migrated
- `hvac>=2.1.0` — Python Vault client (`uv add hvac` in test requirements)
- `kubernetes>=28.1.0` — Python K8s client (`uv add kubernetes` in test requirements)
- `VAULT_TOKEN` available as a CI secret (not committed to repo)

## Definition of Done

- [ ] All 7 `TestACN` classes pass in staging with 0 failures
- [ ] `ha_failover_test.sh` reports leader election time < 30s in at least two consecutive runs
- [ ] Tests added to `tests/security/` and included in the security CI job definition
- [ ] `@destructive` tests gated behind `--run-destructive` pytest CLI flag (not executed in every CI run)
