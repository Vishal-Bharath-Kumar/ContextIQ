# TASK-US051-05 — MinIO Distributed Mode, contextiq-traces Bucket Lifecycle, and Full Integration Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US051-05 |
| User Story | US-051 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / QA |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Deploy MinIO in distributed mode with 4 nodes (4 StatefulSet replicas × 1 drive each) in `contextiq-infra` (AC-5). MinIO's erasure coding distributes data and parity blocks across all 4 nodes, tolerating up to 2 node failures without data loss. A bootstrap script creates the `contextiq-traces` bucket with versioning enabled and a lifecycle policy that transitions objects to a cold storage tier after 90 days and expires them after 1 year (AC-5). MinIO credentials are Vault-injected (AC-6). A Prometheus ServiceMonitor and full integration tests validate all 7 ACs (AC-7).

## Implementation Details

**Technology:** MinIO RELEASE.2024-07-xx, `minio/minio` Helm chart, `mc` MinIO client, Python `aiobotocore>=2.13`

**File locations:**
- `helm/charts/minio/Chart.yaml`
- `helm/charts/minio/values.yaml`
- `helm/charts/minio/values-prod.yaml`
- `scripts/datastore/bootstrap_minio.py` — bucket + lifecycle creation
- `tests/integration/test_datastores.py` — US-051 integration tests
- `argocd/apps/services/minio.yaml`

---

### Helm wrapper

```yaml
# helm/charts/minio/Chart.yaml
apiVersion: v2
name:        minio
description: MinIO distributed object store for ContextIQ
type:        application
version:     0.1.0
dependencies:
  - name:       minio
    version:    "5.x.x"
    repository: https://charts.min.io
```

```yaml
# helm/charts/minio/values.yaml
minio:
  image:
    tag: "RELEASE.2024-07-16T23-46-41Z"    # pin for reproducibility

  # AC-5: 4-node distributed mode
  mode:      distributed
  replicas:  4
  drivesPerNode: 1

  # Credentials via Vault Agent at runtime (AC-6) — not set here
  rootUser:     ""        # overwritten by /vault/secrets/minio.env
  rootPassword: ""

  # Encrypted PVC per node (TASK-US048-04)
  persistence:
    enabled:      true
    storageClass: contextiq-encrypted-gp3
    size:         500Gi    # per pod; 4 × 500 Gi = 2 TB raw

  resources:
    requests: { cpu: "1",    memory: "4Gi" }
    limits:   { cpu: "4",    memory: "16Gi" }

  # AC-6: Vault Agent injects MinIO root credentials
  podAnnotations:
    vault.hashicorp.com/agent-inject:                "true"
    vault.hashicorp.com/role:                        "admin-api"
    vault.hashicorp.com/agent-pre-populate-only:     "true"
    vault.hashicorp.com/agent-inject-secret-minio:   "secret/data/contextiq/minio/root"
    vault.hashicorp.com/agent-inject-template-minio: |
      {{- with secret "secret/data/contextiq/minio/root" -}}
      export MINIO_ROOT_USER="{{ .Data.data.access_key }}"
      export MINIO_ROOT_PASSWORD="{{ .Data.data.secret_key }}"
      {{- end }}

  # TLS (TASK-US048-02)
  tls:
    enabled:    true
    certSecret: minio-tls    # cert-manager Certificate (TASK-US048-01)

  # AC-5: anti-affinity — spread across distinct nodes
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels:
              app: minio
          topologyKey: kubernetes.io/hostname

  # PDB — tolerate 1 node down (MinIO quorum: 4 nodes, can lose 2 for reads but only 1 for writes)
  podDisruptionBudget:
    enabled:        true
    maxUnavailable: 1

  # AC-7: Prometheus metrics
  metrics:
    serviceMonitor:
      enabled:   true
      namespace: contextiq-observability
      additionalLabels:
        app.kubernetes.io/part-of: contextiq

  # MinIO Console (admin UI)
  consoleIngress:
    enabled: true
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod
    hosts: [minio.contextiq.io]
    tls:
      - secretName: minio-console-tls
        hosts:      [minio.contextiq.io]

  # SSE-S3 encryption at rest (TASK-US048-04)
  environment:
    MINIO_KMS_SECRET_KEY: ""    # set via Vault if using SSE-S3 with external KMS
```

```yaml
# helm/charts/minio/values-prod.yaml
minio:
  replicas: 4
  persistence:
    size: 2Ti    # 2 TB per node in production
  resources:
    requests: { cpu: "4",    memory: "16Gi" }
    limits:   { cpu: "8",    memory: "32Gi" }
```

---

### Bootstrap: bucket, versioning, lifecycle

```python
# scripts/datastore/bootstrap_minio.py
"""
AC-5: Create contextiq-traces bucket with versioning and lifecycle rules.
Also creates contextiq-audit-archive (US-044), contextiq-models, contextiq-embeddings.
Idempotent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


MINIO_ALIAS    = "contextiq"
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "https://minio.contextiq-infra.svc.cluster.local:9000")
MINIO_USER     = os.environ.get("MINIO_ROOT_USER",     "")
MINIO_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "")


def mc(*args: str) -> dict:
    """Run a MinIO client command and return parsed JSON output."""
    cmd = ["mc", "--json"] + list(args)
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    output = result.stdout.decode().strip()
    if result.returncode != 0:
        stderr = result.stderr.decode()
        raise RuntimeError(f"mc command failed: {' '.join(args)}\nstderr: {stderr}\nstdout: {output}")
    # mc --json may emit multiple lines; return first line
    first_line = output.split("\n")[0] if output else "{}"
    return json.loads(first_line) if first_line else {}


def main() -> int:
    if not MINIO_USER or not MINIO_PASSWORD:
        print("ERROR: MINIO_ROOT_USER / MINIO_ROOT_PASSWORD not set", flush=True)
        return 1

    # Register alias
    mc("alias", "set", MINIO_ALIAS, MINIO_ENDPOINT, MINIO_USER, MINIO_PASSWORD)
    print(f"MinIO alias set: {MINIO_ALIAS} → {MINIO_ENDPOINT}")

    # --- Bucket definitions ---
    BUCKETS = [
        {
            "name":           "contextiq-traces",
            "versioning":     True,
            # AC-5: 90-day cold transition, 1-year expiry
            "lifecycle":      {
                "Rules": [
                    {
                        "ID":     "contextiq-traces-cold-90d",
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "Transition": {
                            "Days":         90,
                            "StorageClass": "GLACIER",    # adjust to your object store cold tier
                        },
                    },
                    {
                        "ID":     "contextiq-traces-expire-1y",
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "Expiration": {"Days": 365},
                    },
                ]
            },
        },
        {
            "name":       "contextiq-audit-archive",   # US-044 (TASK-US044-03)
            "versioning": True,
            "lifecycle":  {
                "Rules": [
                    {
                        "ID":     "audit-archive-expire-3y",
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "Expiration": {"Days": 1096},
                    },
                ]
            },
        },
        {"name": "contextiq-models",     "versioning": True,  "lifecycle": None},
        {"name": "contextiq-embeddings", "versioning": False, "lifecycle": None},
        {
            "name": "contextiq-postgres-backups",   # US-050 (TASK-US050-01)
            "versioning": False,
            "lifecycle": {
                "Rules": [
                    {
                        "ID": "postgres-backups-expire-30d",
                        "Status": "Enabled",
                        "Filter": {"Prefix": "daily/"},
                        "Expiration": {"Days": 30},
                    },
                ]
            },
        },
    ]

    for bucket in BUCKETS:
        name = bucket["name"]

        # Create bucket (idempotent)
        try:
            mc("mb", "--ignore-existing", f"{MINIO_ALIAS}/{name}")
            print(f"  [OK] Bucket {name} exists or created.")
        except RuntimeError as exc:
            print(f"  [FAIL] Could not create bucket {name}: {exc}")
            return 1

        # Enable SSE-S3 encryption (AC-5, TASK-US048-04)
        mc("encrypt", "set", "SSE-S3", f"{MINIO_ALIAS}/{name}")
        print(f"  [OK] SSE-S3 enabled on {name}.")

        # Enable versioning if required (AC-5: contextiq-traces needs versioning)
        if bucket.get("versioning"):
            mc("version", "enable", f"{MINIO_ALIAS}/{name}")
            print(f"  [OK] Versioning enabled on {name}.")

        # Apply lifecycle rules if defined
        if bucket.get("lifecycle"):
            lifecycle_json = json.dumps(bucket["lifecycle"])
            import tempfile, pathlib
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                f.write(lifecycle_json)
                tmp_path = f.name
            mc("ilm", "import", f"{MINIO_ALIAS}/{name}", tmp_path)
            pathlib.Path(tmp_path).unlink()
            print(f"  [OK] Lifecycle rules applied to {name}.")

    print("\n=== MinIO bootstrap complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/minio.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: minio
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://charts.min.io
    chart:          minio
    targetRevision: "5.x.x"
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-infra
  syncPolicy:
    automated: { prune: false, selfHeal: true }
```

---

### Integration tests — all US-051 ACs

```python
# tests/integration/test_datastores.py
"""
Integration tests for US-051: Polyglot data store deployment.

Prerequisites:
  - All stores running and accessible from within cluster (or via port-forward)
  - Environment vars: QDRANT_URL, NEO4J_URI, NEO4J_PASSWORD, OPENSEARCH_HOST,
    OPENSEARCH_PASSWORD, REDIS_SENTINEL_HOSTS, REDIS_PASSWORD,
    MINIO_ENDPOINT, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD

Run:
    pytest tests/integration/test_datastores.py -v --tb=short
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess

import pytest
import redis.asyncio as aioredis
from neo4j import GraphDatabase
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from redis.asyncio.sentinel import Sentinel


# ---------------------------------------------------------------------------
# AC-1: Qdrant cluster + contextiq_embeddings collection
# ---------------------------------------------------------------------------

class TestAC1_Qdrant:

    def test_qdrant_cluster_has_3_peers(self) -> None:
        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant.contextiq-data.svc.cluster.local:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
            timeout=30,
        )
        info = client.get_cluster_info()
        peer_count = len(info.peers) if info.peers else 0
        assert peer_count == 3, f"Expected 3 Qdrant peers, got {peer_count}"

    def test_contextiq_embeddings_collection_exists(self) -> None:
        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant.contextiq-data.svc.cluster.local:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
        )
        info = client.get_collection("contextiq_embeddings")
        assert info.config.params.vectors.size == 1536, (
            f"Expected 1536 dimensions, got {info.config.params.vectors.size}"
        )
        from qdrant_client.http.models import Distance
        assert info.config.params.vectors.distance == Distance.COSINE, (
            "Expected COSINE distance metric"
        )

    def test_qdrant_vector_upsert_and_search(self) -> None:
        from qdrant_client.http.models import PointStruct
        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant.contextiq-data.svc.cluster.local:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
        )
        client.upsert(
            collection_name="contextiq_embeddings",
            points=[PointStruct(id=999999, vector=[0.1] * 1536, payload={"source_id": "test"})],
        )
        results = client.search(
            collection_name="contextiq_embeddings",
            query_vector=[0.1] * 1536,
            limit=1,
        )
        assert results, "Qdrant search returned no results after upsert"
        client.delete(collection_name="contextiq_embeddings", points_selector=[999999])


# ---------------------------------------------------------------------------
# AC-2: Neo4j cluster + schema constraints
# ---------------------------------------------------------------------------

class TestAC2_Neo4j:

    @pytest.fixture(scope="class")
    def neo4j_driver(self):
        d = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://contextiq-neo4j.contextiq-data.svc.cluster.local:7687"),
            auth=("neo4j", os.environ["NEO4J_PASSWORD"]),
        )
        yield d
        d.close()

    def test_neo4j_cluster_has_3_cores(self, neo4j_driver) -> None:
        with neo4j_driver.session() as s:
            result = s.run("CALL dbms.cluster.overview() YIELD role").data()
        roles = [r["role"] for r in result]
        assert len(roles) == 3, f"Expected 3 cluster members, got {len(roles)}: {roles}"

    def test_neo4j_constraints_exist(self, neo4j_driver) -> None:
        with neo4j_driver.session() as s:
            constraints = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name").data()}
        for expected in ("constraint_service_id", "constraint_repo_id",
                         "constraint_developer_id", "constraint_incident_id"):
            assert expected in constraints, f"Constraint {expected!r} missing"

    def test_neo4j_unique_constraint_enforced(self, neo4j_driver) -> None:
        with neo4j_driver.session() as s:
            s.run("MERGE (:Service {id: 'test-svc-1', name: 'test', namespace: 'default'})")
            with pytest.raises(Exception, match="ConstraintValidationFailed|already exists"):
                s.run("CREATE (:Service {id: 'test-svc-1'})")
            s.run("MATCH (s:Service {id: 'test-svc-1'}) DETACH DELETE s")


# ---------------------------------------------------------------------------
# AC-3: OpenSearch cluster + contextiq_documents index
# ---------------------------------------------------------------------------

class TestAC3_OpenSearch:

    @pytest.fixture(scope="class")
    def os_client(self):
        return OpenSearch(
            hosts=[{"host": os.environ.get("OPENSEARCH_HOST", "opensearch.contextiq-data.svc.cluster.local"), "port": 9200}],
            http_auth=("admin", os.environ["OPENSEARCH_PASSWORD"]),
            use_ssl=True, verify_certs=False,
        )

    def test_opensearch_cluster_green(self, os_client) -> None:
        health = os_client.cluster.health(wait_for_status="green", timeout="30s")
        assert health["number_of_nodes"] == 3
        assert health["status"] == "green"

    def test_contextiq_documents_index_exists(self, os_client) -> None:
        assert os_client.indices.exists(index="contextiq_documents"), (
            "contextiq_documents index not found"
        )

    def test_index_has_required_fields(self, os_client) -> None:
        mapping = os_client.indices.get_mapping(index="contextiq_documents")
        fields = mapping["contextiq_documents"]["mappings"]["properties"]
        for required in ("content", "source_id", "metadata", "indexed_at"):
            assert required in fields, f"Field {required!r} missing from index mapping"

    def test_bm25_similarity(self, os_client) -> None:
        settings = os_client.indices.get_settings(index="contextiq_documents")
        sim = settings["contextiq_documents"]["settings"]["index"].get("similarity", {})
        assert sim.get("default", {}).get("type") == "BM25", "BM25 similarity not configured"


# ---------------------------------------------------------------------------
# AC-4: Redis Sentinel HA + keyspace notifications
# ---------------------------------------------------------------------------

class TestAC4_Redis:

    @pytest.fixture(scope="class")
    def sentinel(self):
        return Sentinel(
            [("redis-headless.contextiq-data.svc.cluster.local", 26379)],
            sentinel_kwargs={"password": os.environ["REDIS_PASSWORD"]},
            password=os.environ["REDIS_PASSWORD"],
            decode_responses=True,
        )

    @pytest.mark.asyncio
    async def test_sentinel_master_discovered(self, sentinel) -> None:
        host, port = await sentinel.discover_master("contextiq-redis")
        assert host, "Sentinel could not discover Redis master"

    @pytest.mark.asyncio
    async def test_sentinel_has_2_replicas(self, sentinel) -> None:
        slaves = await sentinel.discover_slaves("contextiq-redis")
        assert len(slaves) >= 2, f"Expected 2 replicas, got {len(slaves)}"

    @pytest.mark.asyncio
    async def test_keyspace_notifications_enabled(self, sentinel) -> None:
        master = sentinel.master_for("contextiq-redis")
        config = await master.config_get("notify-keyspace-events")
        events = config.get("notify-keyspace-events", "")
        assert "K" in events and "E" in events, (
            f"Keyspace notifications KEA not enabled: {events!r}"
        )
        await master.aclose()


# ---------------------------------------------------------------------------
# AC-5: MinIO distributed + contextiq-traces bucket lifecycle
# ---------------------------------------------------------------------------

class TestAC5_MinIO:

    def test_minio_pods_running(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", "contextiq-infra",
             "-l", "app=minio", "-o", "jsonpath={.items[*].status.phase}"],
            capture_output=True, timeout=15,
        )
        phases = result.stdout.decode().split()
        assert len(phases) == 4 and all(p == "Running" for p in phases), (
            f"Expected 4 Running MinIO pods, got: {phases}"
        )

    def test_contextiq_traces_bucket_exists(self) -> None:
        result = subprocess.run(
            ["mc", "--json", "stat", "contextiq/contextiq-traces"],
            capture_output=True, timeout=15,
        )
        data = json.loads(result.stdout.decode().strip().split("\n")[0])
        assert data.get("status") == "success", "contextiq-traces bucket does not exist"

    def test_versioning_enabled_on_traces(self) -> None:
        result = subprocess.run(
            ["mc", "--json", "version", "info", "contextiq/contextiq-traces"],
            capture_output=True, timeout=15,
        )
        data = json.loads(result.stdout.decode().strip().split("\n")[0])
        assert data.get("status") == "enabled", (
            f"Versioning not enabled on contextiq-traces: {data}"
        )

    def test_lifecycle_rules_present(self) -> None:
        result = subprocess.run(
            ["mc", "--json", "ilm", "ls", "contextiq/contextiq-traces"],
            capture_output=True, timeout=15,
        )
        output = result.stdout.decode()
        assert "365" in output or "1y" in output or "expire" in output.lower(), (
            "1-year expiry lifecycle rule not found on contextiq-traces"
        )


# ---------------------------------------------------------------------------
# AC-6: Vault credentials injected into all store pods
# ---------------------------------------------------------------------------

class TestAC6_VaultCredentials:

    @pytest.mark.parametrize("namespace,label,secret_file", [
        ("contextiq-data",  "app.kubernetes.io/name=qdrant",      "/vault/secrets/qdrant.env"),
        ("contextiq-data",  "app.kubernetes.io/name=redis",       "/vault/secrets/redis.env"),
        ("contextiq-infra", "app=minio",                          "/vault/secrets/minio.env"),
    ])
    def test_vault_secret_file_present(self, namespace: str, label: str, secret_file: str) -> None:
        pods = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-l", label,
             "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True, timeout=15,
        ).stdout.decode().strip()
        assert pods, f"No pod found for {label} in {namespace}"

        result = subprocess.run(
            ["kubectl", "exec", "-n", namespace, pods, "--", "test", "-f", secret_file],
            capture_output=True, timeout=15,
        )
        assert result.returncode == 0, (
            f"Vault secret file {secret_file} not found in {namespace}/{pods}"
        )


# ---------------------------------------------------------------------------
# AC-7: Prometheus ServiceMonitors exist for all stores
# ---------------------------------------------------------------------------

class TestAC7_ServiceMonitors:

    @pytest.mark.parametrize("sm_name", [
        "qdrant", "neo4j", "opensearch", "redis", "minio",
    ])
    def test_servicemonitor_exists(self, sm_name: str) -> None:
        result = subprocess.run(
            ["kubectl", "get", "servicemonitor", sm_name,
             "-n", "contextiq-observability",
             "-o", "jsonpath={.metadata.name}"],
            capture_output=True, timeout=15,
        )
        assert result.returncode == 0 and result.stdout.decode().strip() == sm_name, (
            f"ServiceMonitor '{sm_name}' not found in contextiq-observability"
        )
```

## Acceptance Criteria

- [x] `kubectl get pods -n contextiq-infra -l app=minio` shows 4 Running pods (AC-5)
- [x] `mc stat contextiq/contextiq-traces` returns `status: success` (AC-5)
- [x] `mc version info contextiq/contextiq-traces` shows `status: enabled` (AC-5)
- [x] `mc ilm ls contextiq/contextiq-traces` shows a 90-day transition rule and a 365-day expiry rule (AC-5)
- [x] `bootstrap_minio.py` runs idempotently; all 5 buckets exist with SSE-S3 enabled (AC-5, AC-6)
- [x] `pytest tests/integration/test_datastores.py -v` passes all 7 AC test classes (all ACs)
- [x] `TestAC7_ServiceMonitors` — all 5 ServiceMonitors exist in `contextiq-observability` (AC-7)

## Dependencies

- TASK-US045-01 — `contextiq-data` and `contextiq-infra` namespaces
- TASK-US047-02 — Vault `secret/contextiq/minio/root` KV path must exist
- TASK-US048-04 — `contextiq-encrypted-gp3` StorageClass
- `mc` (MinIO client) available in CI runner for test execution
- TASK-US051-01 through TASK-US051-04 must be complete before integration tests can pass

## Definition of Done

- [x] MinIO distributed cluster stable with all 4 pods Running
- [x] `bootstrap_minio.py` committed and idempotent in staging
- [x] All 5 integration test classes pass in staging with 0 failures
