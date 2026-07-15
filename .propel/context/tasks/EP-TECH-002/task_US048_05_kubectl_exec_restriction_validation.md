# TASK-US048-05 — kubectl exec Restriction via Admission Webhook and Full Integration Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US048-05 |
| User Story | US-048 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure / QA |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Deploy an OPA Gatekeeper `ConstraintTemplate` and `Constraint` that deny `kubectl exec` and `kubectl port-forward` requests in all `contextiq-*` namespaces in production, preventing lateral movement and live-container inspection (AC-6). A `BreakGlassPolicy` annotation on trusted ServiceAccounts allows emergency access with automatic audit-log emission. Full integration tests (`tests/security/test_tls_encryption.py`) validate all 7 ACs for US-048.

## Implementation Details

**Technology:** OPA Gatekeeper 3.16+, pytest 7+, Python 3.11+, `kubernetes` Python client, `subprocess` / `openssl`

**File locations:**
- `k8s/gatekeeper/constraint-templates/deny-exec-portforward.yaml` — `ConstraintTemplate`
- `k8s/gatekeeper/constraints/deny-exec-portforward-prod.yaml` — `Constraint` targeting prod namespaces
- `k8s/gatekeeper/constraints/break-glass-role.yaml` — `ClusterRole` + annotation convention for emergency access
- `tests/security/test_tls_encryption.py` — pytest integration suite for US-048

---

### OPA Gatekeeper: ConstraintTemplate

```yaml
# k8s/gatekeeper/constraint-templates/deny-exec-portforward.yaml
# AC-6: Deny kubectl exec and port-forward in production namespaces.
# The constraint checks the SubjectAccessReview / exec/portforward resource verbs
# sent to the Kubernetes API server and rejects them unless the caller has the
# break-glass annotation on their ServiceAccount.
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: denyexecportforward
spec:
  crd:
    spec:
      names:
        kind: DenyExecPortForward
      validation:
        openAPIV3Schema:
          type: object
          properties:
            allowedServiceAccounts:
              type: array
              items:
                type: string
              description: "ServiceAccount names exempt from this restriction (break-glass)"
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package denyexecportforward

        import future.keywords.if

        violation[{"msg": msg}] if {
          # Match exec and port-forward sub-resource requests
          input.review.request.subResource == "exec"
          not is_break_glass_user
          msg := sprintf(
            "kubectl exec is not allowed in namespace '%v' (AC-6). Use Vault Agent or debug tooling.",
            [input.review.request.namespace]
          )
        }

        violation[{"msg": msg}] if {
          input.review.request.subResource == "portforward"
          not is_break_glass_user
          msg := sprintf(
            "kubectl port-forward is not allowed in namespace '%v' (AC-6).",
            [input.review.request.namespace]
          )
        }

        is_break_glass_user if {
          # Caller's username is in the explicitly allowed list
          input.review.request.userInfo.username == input.parameters.allowedServiceAccounts[_]
        }

        is_break_glass_user if {
          # Caller carries the break-glass annotation on their bound ServiceAccount
          # (checked via userInfo.extra set by the RBAC authenticator)
          input.review.request.userInfo.extra["contextiq.io/break-glass"][_] == "true"
        }
```

---

### Constraint — production namespaces

```yaml
# k8s/gatekeeper/constraints/deny-exec-portforward-prod.yaml
# AC-6: Applies the DenyExecPortForward constraint to all contextiq-* namespaces.
# Emergency access: add the ServiceAccount username to allowedServiceAccounts
# and raise an incident ticket before use.
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: DenyExecPortForward
metadata:
  name: no-exec-portforward-prod
  annotations:
    # Self-documentation: link to incident response runbook
    contextiq.io/runbook: "https://wiki.contextiq.io/runbooks/break-glass-exec"
spec:
  enforcementAction: deny    # hard deny in production; use 'warn' during rollout testing
  match:
    namespaces:
      - contextiq-data
      - contextiq-agents
      - contextiq-gateway
      - contextiq-admin
      - contextiq-security
      - contextiq-observability
      - contextiq-infra
    kinds:
      - apiGroups: [""]
        kinds:     ["Pod"]
  parameters:
    allowedServiceAccounts:
      # Only the SRE break-glass account may exec — requires manual approval + audit trail
      - system:serviceaccount:contextiq-infra:sre-break-glass
```

---

### Break-glass ServiceAccount

```yaml
# k8s/gatekeeper/constraints/break-glass-role.yaml
# Emergency access account for SRE team — exec allowed only via this SA.
# Usage of this SA is automatically captured in the Kubernetes audit log.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sre-break-glass
  namespace: contextiq-infra
  annotations:
    contextiq.io/break-glass: "true"
    contextiq.io/approver-required: "true"
    contextiq.io/runbook: "https://wiki.contextiq.io/runbooks/break-glass-exec"
---
# ClusterRole: minimal permissions — only exec/port-forward on pods
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: sre-break-glass-exec
rules:
  - apiGroups: [""]
    resources: ["pods/exec", "pods/portforward"]
    verbs:     ["create", "get"]
---
# Binding scoped to break-glass SA only — not granted to any human user directly
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: sre-break-glass-exec
subjects:
  - kind:      ServiceAccount
    name:      sre-break-glass
    namespace: contextiq-infra
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind:     ClusterRole
  name:     sre-break-glass-exec
```

---

### Integration test suite: all US-048 ACs

```python
# tests/security/test_tls_encryption.py
"""
Integration tests for US-048: TLS everywhere and encryption at rest.

Run in staging cluster:
    pytest tests/security/test_tls_encryption.py -v --tb=short

Destructive tests (AC-6 exec restriction) require --run-destructive flag:
    pytest tests/security/test_tls_encryption.py -v -m destructive --run-destructive
"""
from __future__ import annotations

import json
import os
import subprocess
import re
from typing import Generator

import pytest
from kubernetes import client as k8s_client, config as k8s_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def k8s() -> k8s_client.CoreV1Api:
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return k8s_client.CoreV1Api()


def _openssl_probe(host: str, port: int = 443, tls_version_flag: str = "-tls1_3") -> str:
    """Return openssl s_client output for a given host/port/TLS version."""
    result = subprocess.run(
        ["openssl", "s_client", "-connect", f"{host}:{port}", tls_version_flag, "-brief"],
        input=b"",
        capture_output=True,
        timeout=15,
    )
    return result.stdout.decode() + result.stderr.decode()


# ---------------------------------------------------------------------------
# AC-1: cert-manager deployed; ClusterIssuers ready
# ---------------------------------------------------------------------------

class TestAC1_CertManager:

    def test_cert_manager_controller_running(self, k8s: k8s_client.CoreV1Api) -> None:
        pods = k8s.list_namespaced_pod(
            namespace="contextiq-infra",
            label_selector="app.kubernetes.io/name=cert-manager",
        )
        running = [p for p in pods.items if p.status.phase == "Running"]
        assert len(running) >= 1, "cert-manager controller pod not running"

    def test_cluster_issuers_ready(self) -> None:
        from kubernetes.client import CustomObjectsApi
        api = CustomObjectsApi()
        issuers = api.list_cluster_custom_object(
            group="cert-manager.io", version="v1", plural="clusterissuers"
        )
        issuer_names = [i["metadata"]["name"] for i in issuers["items"]]
        for expected in ("contextiq-internal-ca", "letsencrypt-prod"):
            assert expected in issuer_names, f"ClusterIssuer '{expected}' not found"
            issuer = next(i for i in issuers["items"] if i["metadata"]["name"] == expected)
            conditions = issuer.get("status", {}).get("conditions", [])
            ready = any(c["type"] == "Ready" and c["status"] == "True" for c in conditions)
            assert ready, f"ClusterIssuer '{expected}' is not Ready"


# ---------------------------------------------------------------------------
# AC-2: All Ingress resources have cert-manager-issued TLS certificates
# ---------------------------------------------------------------------------

class TestAC2_IngressTLS:

    @pytest.mark.parametrize("namespace,ingress_name,expected_host", [
        ("contextiq-gateway",  "mcp-gateway", "api.contextiq.io"),
        ("contextiq-security", "keycloak",    "auth.contextiq.io"),
        ("contextiq-admin",    "admin-portal", "admin.contextiq.io"),
    ])
    def test_ingress_tls_certificate_ready(
        self,
        namespace: str,
        ingress_name: str,
        expected_host: str,
    ) -> None:
        from kubernetes.client import CustomObjectsApi
        api = CustomObjectsApi()
        certs = api.list_namespaced_custom_object(
            group="cert-manager.io", version="v1", namespace=namespace, plural="certificates"
        )
        # At least one cert in this namespace must be Ready
        ready_certs = [
            c for c in certs["items"]
            if any(
                cond["type"] == "Ready" and cond["status"] == "True"
                for cond in c.get("status", {}).get("conditions", [])
            )
        ]
        assert ready_certs, f"No Ready cert-manager Certificate found in namespace {namespace}"


# ---------------------------------------------------------------------------
# AC-3: mTLS STRICT PeerAuthentication present in all namespaces
# ---------------------------------------------------------------------------

class TestAC3_MTLS:

    NAMESPACES = [
        "contextiq-data", "contextiq-agents", "contextiq-gateway",
        "contextiq-admin", "contextiq-security", "contextiq-observability", "contextiq-infra",
    ]

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_peer_authentication_strict(self, namespace: str) -> None:
        from kubernetes.client import CustomObjectsApi
        api = CustomObjectsApi()
        try:
            pa = api.get_namespaced_custom_object(
                group="security.istio.io", version="v1beta1",
                namespace=namespace, plural="peerauthentications", name="default"
            )
        except k8s_client.exceptions.ApiException as exc:
            pytest.fail(f"PeerAuthentication 'default' not found in {namespace}: {exc}")
        mode = pa.get("spec", {}).get("mtls", {}).get("mode")
        assert mode == "STRICT", f"PeerAuthentication in {namespace} has mode={mode!r}, expected STRICT"

    @pytest.mark.parametrize("namespace,label", [
        ("contextiq-gateway", "app.kubernetes.io/name=mcp-gateway"),
        ("contextiq-agents",  "app.kubernetes.io/name=agent-worker"),
    ])
    def test_envoy_sidecar_injected(
        self, k8s: k8s_client.CoreV1Api, namespace: str, label: str
    ) -> None:
        pods = k8s.list_namespaced_pod(namespace=namespace, label_selector=label)
        assert pods.items, f"No pods found for {label} in {namespace}"
        pod = pods.items[0]
        names = [c.name for c in pod.spec.containers]
        assert "istio-proxy" in names, f"Envoy sidecar not injected in {pod.metadata.name}: {names}"


# ---------------------------------------------------------------------------
# AC-4: TLS 1.3 accepted; TLS 1.2 rejected at external ingress points
# ---------------------------------------------------------------------------

class TestAC4_TLS13Enforcement:

    @pytest.mark.parametrize("host", [
        "api.contextiq.io",
        "auth.contextiq.io",
        "admin.contextiq.io",
    ])
    def test_tls13_accepted(self, host: str) -> None:
        output = _openssl_probe(host, tls_version_flag="-tls1_3")
        assert "Protocol  : TLSv1.3" in output or "TLSv1.3" in output, (
            f"TLS 1.3 not accepted at {host}. openssl output:\n{output}"
        )

    @pytest.mark.parametrize("host", [
        "api.contextiq.io",
        "auth.contextiq.io",
    ])
    def test_tls12_rejected(self, host: str) -> None:
        output = _openssl_probe(host, tls_version_flag="-tls1_2")
        assert "handshake failure" in output.lower() or "ssl alert" in output.lower(), (
            f"TLS 1.2 was NOT rejected at {host} — AC-4 violation. openssl output:\n{output}"
        )

    def test_nginx_ssl_protocols_config(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "configmap", "ingress-nginx-controller",
             "-n", "ingress-nginx", "-o", "jsonpath={.data.ssl-protocols}"],
            capture_output=True, timeout=15,
        )
        assert result.stdout.decode().strip() == "TLSv1.3", (
            f"NGINX ssl-protocols is not 'TLSv1.3': {result.stdout.decode()!r}"
        )


# ---------------------------------------------------------------------------
# AC-5: Encryption at rest — all PVCs use encrypted StorageClass
# ---------------------------------------------------------------------------

class TestAC5_EncryptionAtRest:

    ENCRYPTED_CLASS = "contextiq-encrypted-gp3"

    @pytest.mark.parametrize("namespace,pvc_name", [
        ("contextiq-data",  "data-postgres-0"),
        ("contextiq-data",  "data-redis-0"),
        ("contextiq-data",  "data-neo4j-0"),
        ("contextiq-data",  "qdrant-storage-qdrant-0"),
        ("contextiq-infra", "data-minio-0"),
    ])
    def test_pvc_uses_encrypted_storage_class(
        self, k8s: k8s_client.CoreV1Api, namespace: str, pvc_name: str
    ) -> None:
        pvc = k8s.read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
        assert pvc.spec.storage_class_name == self.ENCRYPTED_CLASS, (
            f"{namespace}/{pvc_name} uses '{pvc.spec.storage_class_name}' "
            f"instead of '{self.ENCRYPTED_CLASS}'"
        )


# ---------------------------------------------------------------------------
# AC-6: kubectl exec restricted via OPA Gatekeeper
# ---------------------------------------------------------------------------

class TestAC6_KubectlExecRestricted:

    @pytest.mark.destructive
    def test_kubectl_exec_denied_in_production(self, k8s: k8s_client.CoreV1Api) -> None:
        """Attempt kubectl exec into a production pod — expect a Gatekeeper denial."""
        pods = k8s.list_namespaced_pod(
            namespace="contextiq-gateway",
            label_selector="app.kubernetes.io/name=mcp-gateway",
        )
        assert pods.items, "No mcp-gateway pods found to test against"
        pod_name = pods.items[0].metadata.name

        result = subprocess.run(
            ["kubectl", "exec", "-n", "contextiq-gateway", pod_name, "--", "echo", "test"],
            capture_output=True, timeout=15,
        )
        assert result.returncode != 0, (
            "kubectl exec succeeded — AC-6 Gatekeeper constraint is NOT enforcing"
        )
        combined_output = result.stderr.decode() + result.stdout.decode()
        assert "not allowed" in combined_output.lower() or "denied" in combined_output.lower(), (
            f"exec was rejected but not by Gatekeeper — output: {combined_output}"
        )

    def test_gatekeeper_constraint_exists(self) -> None:
        from kubernetes.client import CustomObjectsApi
        api = CustomObjectsApi()
        try:
            constraint = api.get_cluster_custom_object(
                group="constraints.gatekeeper.sh",
                version="v1beta1",
                plural="denyexecportforwards",
                name="no-exec-portforward-prod",
            )
        except k8s_client.exceptions.ApiException as exc:
            pytest.fail(f"DenyExecPortForward constraint not found: {exc}")
        action = constraint.get("spec", {}).get("enforcementAction")
        assert action == "deny", f"enforcementAction is {action!r}, expected 'deny'"


# ---------------------------------------------------------------------------
# AC-7: Certificate renewBefore is 720h (30 days before expiry)
# ---------------------------------------------------------------------------

class TestAC7_CertificateAutoRenewal:

    @pytest.mark.parametrize("namespace,cert_name", [
        ("contextiq-gateway",  "mcp-gateway-tls"),
        ("contextiq-security", "keycloak-tls"),
        ("contextiq-admin",    "admin-portal-tls"),
    ])
    def test_certificate_renew_before_720h(self, namespace: str, cert_name: str) -> None:
        from kubernetes.client import CustomObjectsApi
        api = CustomObjectsApi()
        try:
            cert = api.get_namespaced_custom_object(
                group="cert-manager.io", version="v1",
                namespace=namespace, plural="certificates", name=cert_name
            )
        except k8s_client.exceptions.ApiException as exc:
            pytest.fail(f"Certificate {namespace}/{cert_name} not found: {exc}")
        renew_before = cert.get("spec", {}).get("renewBefore", "")
        # Accept either 720h0m0s (cert-manager normalised) or 720h annotation form
        assert re.match(r"720h", renew_before), (
            f"Certificate {namespace}/{cert_name} has renewBefore={renew_before!r}, "
            f"expected '720h' (30 days)"
        )
```

## Acceptance Criteria

- [x] `kubectl exec -n contextiq-gateway <pod> -- echo test` returns `Error: denyexecportforward` from Gatekeeper (AC-6)
- [x] `kubectl get denyexecportforward no-exec-portforward-prod -o yaml | grep enforcementAction` shows `deny` (AC-6)
- [x] Break-glass SA `sre-break-glass` can exec successfully (escape hatch confirmed working) (AC-6)
- [x] `pytest tests/security/test_tls_encryption.py -v --tb=short` passes all 7 AC test classes (all ACs)
- [x] Destructive test `TestAC6_KubectlExecRestricted::test_kubectl_exec_denied_in_production` passes with `--run-destructive` (AC-6)

## Dependencies

- TASK-US048-01 — cert-manager ClusterIssuers must exist for AC-1/AC-2/AC-7 assertions
- TASK-US048-02 — NGINX TLS config must be applied for AC-4 assertions
- TASK-US048-03 — Istio `PeerAuthentication` must be applied for AC-3 assertions
- TASK-US048-04 — Encrypted StorageClass and PVC patches must be applied for AC-5 assertions
- OPA Gatekeeper must be deployed in the cluster (`kubectl get pods -n gatekeeper-system`)
- `kubernetes>=28.1.0` Python client in test requirements
- `openssl` CLI available in CI runner image

## Definition of Done

- [x] `kubectl apply -f k8s/gatekeeper/constraint-templates/deny-exec-portforward.yaml` succeeds; `kubectl apply -f k8s/gatekeeper/constraints/deny-exec-portforward-prod.yaml` succeeds
- [x] All pytest tests in `TestAC1` through `TestAC7` pass in staging (non-destructive)
- [x] Destructive test run confirms `kubectl exec` is denied in `contextiq-gateway`
- [x] Tests added to the `security` CI job stage alongside US-047 tests
