# TASK-US051-01 — Qdrant 3-Node Cluster and contextiq_embeddings Collection

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US051-01 |
| User Story | US-051 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Deploy Qdrant in distributed cluster mode with 3 nodes in `contextiq-data` (AC-1). Qdrant's built-in Raft consensus handles shard replication across the 3 nodes; `replication_factor: 2` ensures each shard has a copy on two nodes so the cluster tolerates one node failure without data loss. After the cluster is up, a Python bootstrap script creates the `contextiq_embeddings` collection with `text-embedding-3-small` vector dimensions (1536) and cosine distance metric. The Vault Agent sidecar injects the Qdrant API key (AC-6); a Prometheus ServiceMonitor scrapes the `/metrics` endpoint (AC-7).

## Implementation Details

**Technology:** Qdrant 1.9.x, Qdrant Helm chart (`qdrant/qdrant`), Python `qdrant-client>=1.9`, Kubernetes StatefulSet

**File locations:**
- `helm/charts/qdrant/Chart.yaml`
- `helm/charts/qdrant/values.yaml`
- `helm/charts/qdrant/values-prod.yaml`
- `scripts/datastore/bootstrap_qdrant.py` — collection creation script
- `argocd/apps/services/qdrant.yaml`

---

### Helm wrapper

```yaml
# helm/charts/qdrant/Chart.yaml
apiVersion: v2
name:        qdrant
description: Qdrant vector database for ContextIQ
type:        application
version:     0.1.0
dependencies:
  - name:       qdrant
    version:    "0.10.x"    # tracks Qdrant 1.9.x
    repository: https://qdrant.github.io/qdrant-helm
```

```yaml
# helm/charts/qdrant/values.yaml
qdrant:
  replicaCount: 3    # AC-1: 3-node distributed cluster

  image:
    tag: "v1.9.7"    # pin for reproducibility

  config:
    cluster:
      enabled: true           # AC-1: enable distributed mode
      consensus:
        tick_period_ms: 100
    service:
      api_key: ""             # provided by Vault Agent at runtime (AC-6) — not set here
    storage:
      # Encrypted PVC (TASK-US048-04)
      storage_path: /qdrant/storage

  persistence:
    enabled:      true
    storageClass: contextiq-encrypted-gp3
    size:         50Gi

  resources:
    requests: { cpu: "500m",  memory: "2Gi" }
    limits:   { cpu: "2",     memory: "8Gi" }

  # AC-6: Vault Agent injects the API key
  podAnnotations:
    vault.hashicorp.com/agent-inject:                 "true"
    vault.hashicorp.com/role:                         "agent-worker"
    vault.hashicorp.com/agent-pre-populate-only:      "true"    # init-only; key is static
    vault.hashicorp.com/agent-inject-secret-qdrant:   "secret/data/contextiq/qdrant/api-key"
    vault.hashicorp.com/agent-inject-template-qdrant: |
      {{- with secret "secret/data/contextiq/qdrant/api-key" -}}
      export QDRANT__SERVICE__API_KEY="{{ .Data.data.api_key }}"
      {{- end }}

  # AC-1: spread nodes across distinct K8s nodes
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels:
              app.kubernetes.io/name: qdrant
          topologyKey: kubernetes.io/hostname

  # AC-7: Prometheus metrics
  metrics:
    serviceMonitor:
      enabled:   true
      namespace: contextiq-observability
      labels:
        app.kubernetes.io/part-of: contextiq

  # PodDisruptionBudget — tolerate 1 node down
  podDisruptionBudget:
    enabled:      true
    maxUnavailable: 1
```

```yaml
# helm/charts/qdrant/values-prod.yaml
qdrant:
  persistence:
    size: 200Gi
  resources:
    requests: { cpu: "2",  memory: "8Gi" }
    limits:   { cpu: "8",  memory: "32Gi" }
```

---

### Bootstrap: create `contextiq_embeddings` collection

```python
# scripts/datastore/bootstrap_qdrant.py
"""
Create the contextiq_embeddings Qdrant collection.
AC-1: 1536-dimensional vectors (text-embedding-3-small), cosine distance.
Run once after Qdrant cluster is healthy. Idempotent.
"""
from __future__ import annotations

import os
import sys

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    VectorParams,
    VectorsConfig,
)

QDRANT_URL     = os.environ.get("QDRANT_URL",     "http://qdrant.contextiq-data.svc.cluster.local:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTION     = "contextiq_embeddings"


def main() -> int:
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None, timeout=30)

    # Verify cluster health before attempting collection creation
    cluster_info = client.get_cluster_info()
    peer_count = len(cluster_info.peers) if cluster_info.peers else 0
    print(f"Qdrant cluster peers: {peer_count}")
    if peer_count < 3:
        print(f"WARNING: Expected 3 peers, got {peer_count}. Proceeding anyway.")

    # Idempotent: skip if collection already exists
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION in existing:
        print(f"Collection '{COLLECTION}' already exists — skipping creation.")
        info = client.get_collection(COLLECTION)
        print(f"  vectors_config: {info.config.params.vectors}")
        return 0

    print(f"Creating collection '{COLLECTION}'...")
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorsConfig(
            # AC-1: text-embedding-3-small dimension = 1536, cosine distance
            params=VectorParams(
                size=1536,
                distance=Distance.COSINE,
                on_disk=True,     # keep vectors on disk for large collections
            )
        ),
        # AC-1: replication_factor=2 for fault tolerance (1 node failure tolerated)
        replication_factor=2,
        write_consistency_factor=1,     # majority not required for writes — favour availability
        hnsw_config=HnswConfigDiff(
            m=16,                       # HNSW M parameter — 16 is a good default for 1536-d
            ef_construct=100,           # higher = better recall, slower index build
            full_scan_threshold=10_000, # switch to full-scan for small result sets
        ),
        optimizers_config=OptimizersConfigDiff(
            indexing_threshold=10_000,  # build HNSW index after 10k vectors in segment
        ),
    )

    # Create a payload index on source_id for filtered vector search
    client.create_payload_index(
        collection_name=COLLECTION,
        field_name="source_id",
        field_schema="keyword",
    )
    client.create_payload_index(
        collection_name=COLLECTION,
        field_name="chunk_index",
        field_schema="integer",
    )

    print(f"Collection '{COLLECTION}' created successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/qdrant.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: qdrant
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://qdrant.github.io/qdrant-helm
    chart:          qdrant
    targetRevision: "0.10.x"
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: false, selfHeal: true }
```

## Acceptance Criteria

- [ ] `kubectl get pods -n contextiq-data -l app.kubernetes.io/name=qdrant` shows 3 pods Running (AC-1)
- [ ] `curl http://qdrant.contextiq-data.svc.cluster.local:6333/cluster` shows `peer_count: 3` and `status: "enabled"` (AC-1)
- [ ] `python scripts/datastore/bootstrap_qdrant.py` completes; `curl .../collections/contextiq_embeddings` shows `"size": 1536, "distance": "Cosine"` (AC-1)
- [ ] `/vault/secrets/qdrant.env` present in Qdrant pod — Vault API key injected (AC-6)
- [ ] `kubectl get servicemonitor qdrant -n contextiq-observability` exists; Prometheus scrapes `/metrics` (AC-7)

## Dependencies

- TASK-US045-01 — `contextiq-data` namespace
- TASK-US047-02 — Vault `secret/contextiq/qdrant/api-key` must exist
- TASK-US048-04 — `contextiq-encrypted-gp3` StorageClass

## Definition of Done

- [ ] Qdrant StatefulSet stable with 3 Running pods
- [ ] `bootstrap_qdrant.py` committed and runs idempotently in staging
- [ ] Collection visible in Qdrant web UI at `http://qdrant.contextiq-data.svc.cluster.local:6333/dashboard`
