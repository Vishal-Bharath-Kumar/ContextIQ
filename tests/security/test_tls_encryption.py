"""
Integration tests for US-048: TLS everywhere and encryption at rest.

Fixtures (k8s, --run-destructive gate) are inherited from tests/security/conftest.py.

Run non-destructive tests in staging:
    pytest tests/security/test_tls_encryption.py -v --tb=short

Include exec-restriction destructive test:
    pytest tests/security/test_tls_encryption.py -v --tb=short --run-destructive
"""
from __future__ import annotations

import re
import subprocess

import pytest
from kubernetes import client as k8s_client


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _openssl_probe(host: str, port: int = 443, tls_version_flag: str = "-tls1_3") -> str:
    """Return combined stdout+stderr from an openssl s_client probe."""
    result = subprocess.run(
        [
            "openssl", "s_client",
            "-connect",    f"{host}:{port}",
            "-servername", host,          # SNI — required for virtual-hosted TLS endpoints
            tls_version_flag,
            "-brief",
        ],
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
        assert len(running) >= 1, "cert-manager controller pod not running in contextiq-infra"

    def test_cluster_issuers_ready(self) -> None:
        api = k8s_client.CustomObjectsApi()
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
        ("contextiq-gateway",  "mcp-gateway",  "api.contextiq.io"),
        ("contextiq-security", "keycloak",     "auth.contextiq.io"),
        ("contextiq-admin",    "admin-portal", "admin.contextiq.io"),
    ])
    def test_ingress_tls_certificate_ready(
        self,
        namespace: str,
        ingress_name: str,
        expected_host: str,
    ) -> None:
        api = k8s_client.CustomObjectsApi()
        certs = api.list_namespaced_custom_object(
            group="cert-manager.io", version="v1",
            namespace=namespace, plural="certificates",
        )
        ready_certs = [
            c for c in certs["items"]
            if any(
                cond["type"] == "Ready" and cond["status"] == "True"
                for cond in c.get("status", {}).get("conditions", [])
            )
        ]
        assert ready_certs, (
            f"No Ready cert-manager Certificate found in namespace {namespace}"
        )


# ---------------------------------------------------------------------------
# AC-3: mTLS STRICT PeerAuthentication present in all contextiq-* namespaces
# ---------------------------------------------------------------------------

class TestAC3_MTLS:

    NAMESPACES = [
        "contextiq-data", "contextiq-agents", "contextiq-gateway",
        "contextiq-admin", "contextiq-security", "contextiq-observability", "contextiq-infra",
    ]

    @pytest.mark.parametrize("namespace", NAMESPACES)
    def test_peer_authentication_strict(self, namespace: str) -> None:
        api = k8s_client.CustomObjectsApi()
        try:
            pa = api.get_namespaced_custom_object(
                group="security.istio.io", version="v1beta1",
                namespace=namespace, plural="peerauthentications", name="default",
            )
        except k8s_client.exceptions.ApiException as exc:
            pytest.fail(f"PeerAuthentication 'default' not found in {namespace}: {exc}")
        mode = pa.get("spec", {}).get("mtls", {}).get("mode")
        assert mode == "STRICT", (
            f"PeerAuthentication in {namespace} has mode={mode!r}, expected STRICT"
        )

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
        assert "istio-proxy" in names, (
            f"Envoy sidecar not injected in {pod.metadata.name}; containers: {names}"
        )


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
        # -brief outputs "Protocol version: TLSv1.3"; without -brief: "Protocol  : TLSv1.3"
        assert "TLSv1.3" in output, (
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
            capture_output=True,
            timeout=15,
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

    def test_gatekeeper_constraint_exists(self) -> None:
        api = k8s_client.CustomObjectsApi()
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

    @pytest.mark.destructive
    def test_kubectl_exec_denied_in_production(self, k8s: k8s_client.CoreV1Api) -> None:
        """Attempt kubectl exec into a production pod — Gatekeeper must deny the request."""
        pods = k8s.list_namespaced_pod(
            namespace="contextiq-gateway",
            label_selector="app.kubernetes.io/name=mcp-gateway",
        )
        assert pods.items, "No mcp-gateway pods found to test against"
        pod_name = pods.items[0].metadata.name

        result = subprocess.run(
            ["kubectl", "exec", "-n", "contextiq-gateway", pod_name, "--", "echo", "test"],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode != 0, (
            "kubectl exec succeeded — AC-6 Gatekeeper constraint is NOT enforcing"
        )
        combined = result.stderr.decode() + result.stdout.decode()
        assert "not allowed" in combined.lower() or "denied" in combined.lower(), (
            f"exec was rejected but not by Gatekeeper — output: {combined}"
        )


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
        api = k8s_client.CustomObjectsApi()
        try:
            cert = api.get_namespaced_custom_object(
                group="cert-manager.io", version="v1",
                namespace=namespace, plural="certificates", name=cert_name,
            )
        except k8s_client.exceptions.ApiException as exc:
            pytest.fail(f"Certificate {namespace}/{cert_name} not found: {exc}")
        renew_before: str = cert.get("spec", {}).get("renewBefore", "")
        # cert-manager normalises "720h" annotation to "720h0m0s" in the spec;
        # re.match anchors at the start so "720h" matches "720h0m0s" correctly.
        assert re.match(r"720h", renew_before), (
            f"Certificate {namespace}/{cert_name} has renewBefore={renew_before!r}, "
            f"expected '720h' (30 days)"
        )
