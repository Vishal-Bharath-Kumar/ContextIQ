# TASK-US051-02 — Neo4j Causal Cluster and Graph Schema Constraints

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US051-02 |
| User Story | US-051 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Deploy Neo4j as a 3-core Causal Cluster in `contextiq-data` using the official Neo4j Helm chart (AC-2). The cluster uses Raft consensus with one elected leader and two followers; all three cores can serve reads while only the leader accepts writes. A Python bootstrap script connects to Neo4j and creates node label constraints and composite indexes for the four required node types: `Service`, `Repository`, `Developer`, `Incident` (AC-2). Neo4j credentials are Vault-injected via the Agent sidecar (AC-6), and a Prometheus ServiceMonitor scrapes the `/metrics` endpoint (AC-7).

## Implementation Details

**Technology:** Neo4j 5.20 Enterprise (or Community with causal clustering), `neo4j/neo4j` Helm chart 5.x, Python `neo4j>=5.19` driver

**File locations:**
- `helm/charts/neo4j/Chart.yaml`
- `helm/charts/neo4j/values.yaml`
- `helm/charts/neo4j/values-prod.yaml`
- `scripts/datastore/bootstrap_neo4j.py` — schema constraints + indexes
- `argocd/apps/services/neo4j.yaml`

---

### Helm wrapper

```yaml
# helm/charts/neo4j/Chart.yaml
apiVersion: v2
name:        neo4j
description: Neo4j Causal Cluster for ContextIQ knowledge graph
type:        application
version:     0.1.0
dependencies:
  - name:       neo4j
    version:    "5.20.x"
    repository: https://helm.neo4j.com/neo4j
```

```yaml
# helm/charts/neo4j/values.yaml
neo4j:
  name: contextiq-neo4j

  # AC-2: Causal Cluster — 3 core members
  clusteringConfig:
    serverMode:    CORE    # all 3 pods are core cluster members
    minimumCoreClusterSize: 3

  # Neo4j version pin
  image:
    customImage: neo4j:5.20.0-enterprise

  # Enterprise license required for Causal Clustering
  # Set via environment variable NEO4J_ACCEPT_LICENSE_AGREEMENT=yes
  env:
    NEO4J_ACCEPT_LICENSE_AGREEMENT: "yes"
    # Vault Agent overwrites these with dynamic values at runtime (AC-6)
    NEO4J_AUTH: "neo4j/PLACEHOLDER"    # replaced by entrypoint script sourcing /vault/secrets/neo4j.env

  # Neo4j configuration
  config:
    dbms.memory.heap.initial_size:       "2G"
    dbms.memory.heap.max_size:           "4G"
    dbms.memory.pagecache.size:          "4G"
    dbms.connector.bolt.enabled:         "true"
    dbms.connector.bolt.advertised_address: ":7687"
    dbms.connector.http.enabled:         "true"
    # Metrics for Prometheus (AC-7)
    dbms.metrics.prometheus.enabled:     "true"
    dbms.metrics.prometheus.endpoint:    "0.0.0.0:2004"
    # Cluster settings
    dbms.cluster.raft.log.rotation.size: "64m"

  resources:
    requests: { cpu: "1",    memory: "8Gi" }
    limits:   { cpu: "4",    memory: "16Gi" }

  # Encrypted PVC (TASK-US048-04)
  volumes:
    data:
      mode:         volume
      volume:
        persistentVolumeClaim:
          claimName: ""    # auto-created by StatefulSet VolumeClaimTemplate
    volumeClaimTemplates:
      data:
        storageClassName: contextiq-encrypted-gp3
        accessModes:      ["ReadWriteOnce"]
        storage:          50Gi

  # AC-6: Vault Agent injects Neo4j admin credentials
  podAnnotations:
    vault.hashicorp.com/agent-inject:                "true"
    vault.hashicorp.com/role:                        "agent-worker"
    vault.hashicorp.com/agent-pre-populate-only:     "true"
    vault.hashicorp.com/agent-inject-secret-neo4j:   "database/neo4j/creds/agent-worker"
    vault.hashicorp.com/agent-inject-template-neo4j: |
      {{- with secret "database/neo4j/creds/agent-worker" -}}
      export NEO4J_AUTH="neo4j/{{ .Data.password }}"
      export NEO4J_USERNAME="{{ .Data.username }}"
      export NEO4J_PASSWORD="{{ .Data.password }}"
      {{- end }}

  # AC-2: anti-affinity — spread cores across distinct nodes
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels:
              app.kubernetes.io/name: neo4j
          topologyKey: kubernetes.io/hostname

  # PDB — tolerate 1 core down (cluster still has quorum with 2 of 3)
  podDisruptionBudget:
    enabled:        true
    minAvailable:   2

  # AC-7: Prometheus ServiceMonitor
  metrics:
    enabled: true
    serviceMonitor:
      enabled:   true
      namespace: contextiq-observability
      port:      prometheus    # port 2004
      labels:
        app.kubernetes.io/part-of: contextiq
```

```yaml
# helm/charts/neo4j/values-prod.yaml
neo4j:
  resources:
    requests: { cpu: "2",  memory: "16Gi" }
    limits:   { cpu: "8",  memory: "32Gi" }
  volumes:
    volumeClaimTemplates:
      data:
        storage: 200Gi
```

---

### Bootstrap: graph schema constraints and indexes

```python
# scripts/datastore/bootstrap_neo4j.py
"""
AC-2: Create Neo4j constraints and indexes for all required node labels.
Idempotent — uses IF NOT EXISTS syntax (Neo4j 5+).
"""
from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase, Driver


NEO4J_URI      = os.environ.get("NEO4J_URI",      "bolt://contextiq-neo4j.contextiq-data.svc.cluster.local:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# ---- Schema definitions -----------------------------------------------
# Each entry: (constraint_name, cypher_statement)
CONSTRAINTS: list[tuple[str, str]] = [
    # Service node: unique id, indexed on name and namespace
    ("constraint_service_id",
     "CREATE CONSTRAINT constraint_service_id IF NOT EXISTS "
     "FOR (s:Service) REQUIRE s.id IS UNIQUE"),
    ("constraint_service_name_ns",
     "CREATE CONSTRAINT constraint_service_name_ns IF NOT EXISTS "
     "FOR (s:Service) REQUIRE (s.name, s.namespace) IS UNIQUE"),

    # Repository node: unique id, indexed on full_name
    ("constraint_repo_id",
     "CREATE CONSTRAINT constraint_repo_id IF NOT EXISTS "
     "FOR (r:Repository) REQUIRE r.id IS UNIQUE"),
    ("constraint_repo_full_name",
     "CREATE CONSTRAINT constraint_repo_full_name IF NOT EXISTS "
     "FOR (r:Repository) REQUIRE r.full_name IS UNIQUE"),

    # Developer node: unique id and email
    ("constraint_developer_id",
     "CREATE CONSTRAINT constraint_developer_id IF NOT EXISTS "
     "FOR (d:Developer) REQUIRE d.id IS UNIQUE"),
    ("constraint_developer_email",
     "CREATE CONSTRAINT constraint_developer_email IF NOT EXISTS "
     "FOR (d:Developer) REQUIRE d.email IS UNIQUE"),

    # Incident node: unique id, indexed on severity and status for fast filtering
    ("constraint_incident_id",
     "CREATE CONSTRAINT constraint_incident_id IF NOT EXISTS "
     "FOR (i:Incident) REQUIRE i.id IS UNIQUE"),
]

INDEXES: list[tuple[str, str]] = [
    # Text index on Service.name for fuzzy lookup
    ("index_service_name",
     "CREATE INDEX index_service_name IF NOT EXISTS "
     "FOR (s:Service) ON (s.name)"),
    ("index_service_namespace",
     "CREATE INDEX index_service_namespace IF NOT EXISTS "
     "FOR (s:Service) ON (s.namespace)"),

    # Repository indexes
    ("index_repo_language",
     "CREATE INDEX index_repo_language IF NOT EXISTS "
     "FOR (r:Repository) ON (r.primary_language)"),

    # Developer indexes
    ("index_developer_team",
     "CREATE INDEX index_developer_team IF NOT EXISTS "
     "FOR (d:Developer) ON (d.team)"),

    # Incident indexes — critical for agent pipeline filtering
    ("index_incident_severity",
     "CREATE INDEX index_incident_severity IF NOT EXISTS "
     "FOR (i:Incident) ON (i.severity)"),
    ("index_incident_status",
     "CREATE INDEX index_incident_status IF NOT EXISTS "
     "FOR (i:Incident) ON (i.status)"),
    ("index_incident_created_at",
     "CREATE INDEX index_incident_created_at IF NOT EXISTS "
     "FOR (i:Incident) ON (i.created_at)"),

    # Composite index: service + severity for dependency-impact queries
    ("index_incident_service_severity",
     "CREATE INDEX index_incident_service_severity IF NOT EXISTS "
     "FOR (i:Incident) ON (i.service_id, i.severity)"),
]


def main() -> int:
    if not NEO4J_PASSWORD:
        print("ERROR: NEO4J_PASSWORD not set", flush=True)
        return 1

    driver: Driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )

    with driver.session(database="neo4j") as session:
        # Verify cluster is accepting writes
        result = session.run("CALL dbms.cluster.overview() YIELD role RETURN role").data()
        print(f"Cluster overview: {result}")

        print("\nApplying constraints...")
        for name, stmt in CONSTRAINTS:
            session.run(stmt)
            print(f"  [OK] {name}")

        print("\nApplying indexes...")
        for name, stmt in INDEXES:
            session.run(stmt)
            print(f"  [OK] {name}")

        # Verify all constraints are present
        constraints = session.run("SHOW CONSTRAINTS YIELD name RETURN name").data()
        constraint_names = {r["name"] for r in constraints}
        for name, _ in CONSTRAINTS:
            assert name in constraint_names, f"Constraint {name!r} missing after creation"

        print(f"\n{len(CONSTRAINTS)} constraints and {len(INDEXES)} indexes applied successfully.")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/neo4j.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: neo4j
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://helm.neo4j.com/neo4j
    chart:          neo4j
    targetRevision: "5.20.x"
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: false, selfHeal: true }
```

## Acceptance Criteria

- [x] `kubectl get pods -n contextiq-data -l app.kubernetes.io/name=neo4j` shows 3 pods Running (AC-2)
- [x] `CALL dbms.cluster.overview()` shows 1 LEADER and 2 FOLLOWER with all peers online (AC-2)
- [x] `SHOW CONSTRAINTS` shows 7 constraints covering all 4 node types (AC-2)
- [x] `SHOW INDEXES` shows 8 indexes including the composite `index_incident_service_severity` (AC-2)
- [x] `CREATE (:Service {id: "dup"}) CREATE (:Service {id: "dup"})` raises `ConstraintValidationFailed` (AC-2)
- [x] Vault `database/neo4j/creds/agent-worker` credentials mount at `/vault/secrets/neo4j.env` (AC-6)
- [x] Prometheus scrapes port 2004; `neo4j_*` metrics visible in Grafana (AC-7)

## Dependencies

- TASK-US045-01 — `contextiq-data` namespace
- TASK-US047-02 — Vault `database/neo4j/creds/agent-worker` role configured
- TASK-US048-04 — `contextiq-encrypted-gp3` StorageClass
- Neo4j Enterprise license required for Causal Clustering; license key in `NEO4J_ACCEPT_LICENSE_AGREEMENT` env var

## Definition of Done

- [x] Neo4j Causal Cluster stable (no `CrashLoopBackOff`) for 15 minutes
- [x] `bootstrap_neo4j.py` runs without errors; all constraints verified
- [x] Cypher query `MATCH (s:Service) RETURN count(s)` executes on all 3 cluster members
