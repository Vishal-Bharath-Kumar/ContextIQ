# TASK-US051-03 — OpenSearch 3-Node Cluster and contextiq_documents Index

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US051-03 |
| User Story | US-051 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Deploy OpenSearch as a 3-node cluster in `contextiq-data` using the OpenSearch Helm chart (AC-3). All three nodes act as master-eligible data nodes so the cluster has quorum (2-of-3) and can tolerate one node failure. A Python bootstrap script creates the `contextiq_documents` index with a `bm25` (BM25) analyzer and explicit field mappings for `content`, `source_id`, `metadata`, and `indexed_at` (AC-3). The OpenSearch admin password is Vault-injected via sidecar (AC-6); a Prometheus ServiceMonitor scrapes `/metrics` (AC-7).

## Implementation Details

**Technology:** OpenSearch 2.14.x, `opensearch-project/helm-charts` (`opensearch`), Python `opensearch-py>=2.6`

**File locations:**
- `helm/charts/opensearch/Chart.yaml`
- `helm/charts/opensearch/values.yaml`
- `helm/charts/opensearch/values-prod.yaml`
- `scripts/datastore/bootstrap_opensearch.py` — index creation
- `argocd/apps/services/opensearch.yaml`

---

### Helm wrapper

```yaml
# helm/charts/opensearch/Chart.yaml
apiVersion: v2
name:        opensearch
description: OpenSearch 3-node cluster for ContextIQ full-text search
type:        application
version:     0.1.0
dependencies:
  - name:       opensearch
    version:    "2.x.x"
    repository: https://opensearch-project.github.io/helm-charts
```

```yaml
# helm/charts/opensearch/values.yaml
opensearch:
  image:
    tag: "2.14.0"    # pin for reproducibility

  # AC-3: 3-node cluster — all nodes master-eligible and data nodes
  replicas: 3

  roles:
    - master
    - data
    - ingest

  # Cluster settings
  config:
    opensearch.yml: |
      cluster.name: contextiq-opensearch
      # AC-3: minimum 2 master-eligible nodes for quorum
      cluster.initial_master_nodes:
        - contextiq-opensearch-0
        - contextiq-opensearch-1
        - contextiq-opensearch-2
      node.max_local_storage_nodes: 1

      # Security: use OpenSearch Security plugin (HTTPS + basic auth)
      plugins.security.ssl.transport.pemcert_filepath:     tls/tls.crt
      plugins.security.ssl.transport.pemkey_filepath:      tls/tls.key
      plugins.security.ssl.transport.pemtrustedcas_filepath: tls/ca.crt
      plugins.security.ssl.http.enabled:                   true
      plugins.security.ssl.http.pemcert_filepath:          tls/tls.crt
      plugins.security.ssl.http.pemkey_filepath:           tls/tls.key
      plugins.security.ssl.http.pemtrustedcas_filepath:    tls/ca.crt
      plugins.security.allow_default_init_securityindex:   true
      plugins.security.authcz.admin_dn:
        - "CN=opensearch-admin,O=ContextIQ"
      plugins.security.nodes_dn:
        - "CN=opensearch-node,O=ContextIQ"

  javaOpts: "-Xmx2g -Xms2g"

  resources:
    requests: { cpu: "500m",  memory: "4Gi" }
    limits:   { cpu: "2",     memory: "8Gi" }

  # Encrypted PVC (TASK-US048-04)
  persistence:
    enabled:      true
    storageClass: contextiq-encrypted-gp3
    size:         50Gi

  # AC-6: Vault Agent injects admin credentials
  podAnnotations:
    vault.hashicorp.com/agent-inject:                      "true"
    vault.hashicorp.com/role:                              "indexing-service"
    vault.hashicorp.com/agent-pre-populate-only:           "true"
    vault.hashicorp.com/agent-inject-secret-opensearch:    "secret/data/contextiq/opensearch/admin"
    vault.hashicorp.com/agent-inject-template-opensearch: |
      {{- with secret "secret/data/contextiq/opensearch/admin" -}}
      export OPENSEARCH_INITIAL_ADMIN_PASSWORD="{{ .Data.data.password }}"
      export OPENSEARCH_PASSWORD="{{ .Data.data.password }}"
      {{- end }}

  # AC-3: anti-affinity across distinct nodes
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels:
              app.kubernetes.io/name: opensearch
          topologyKey: kubernetes.io/hostname

  # PDB — tolerate 1 node down
  podDisruptionBudget:
    enabled:        true
    maxUnavailable: 1

  # AC-7: Prometheus metrics via opensearch-exporter
  metrics:
    enabled:   true
    serviceMonitor:
      enabled:   true
      namespace: contextiq-observability
      labels:
        app.kubernetes.io/part-of: contextiq
```

```yaml
# helm/charts/opensearch/values-prod.yaml
opensearch:
  javaOpts: "-Xmx6g -Xms6g"
  resources:
    requests: { cpu: "2",  memory: "12Gi" }
    limits:   { cpu: "8",  memory: "16Gi" }
  persistence:
    size: 200Gi
```

---

### Bootstrap: create `contextiq_documents` index

```python
# scripts/datastore/bootstrap_opensearch.py
"""
AC-3: Create the contextiq_documents OpenSearch index with BM25 analyzer
and explicit field mappings.
Idempotent — skips creation if index already exists.
"""
from __future__ import annotations

import os
import sys

from opensearchpy import OpenSearch, RequestError

OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "opensearch.contextiq-data.svc.cluster.local")
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASSWORD", "")
INDEX_NAME      = "contextiq_documents"


def main() -> int:
    if not OPENSEARCH_PASS:
        print("ERROR: OPENSEARCH_PASSWORD not set", flush=True)
        return 1

    client = OpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
        use_ssl=True,
        verify_certs=True,
        ssl_show_warn=False,
    )

    # Verify cluster health
    health = client.cluster.health(wait_for_status="green", timeout="60s")
    print(f"Cluster health: {health['status']} — nodes: {health['number_of_nodes']}")
    if health["number_of_nodes"] < 3:
        print(f"WARNING: Expected 3 nodes, got {health['number_of_nodes']}")

    # Idempotent: skip if index already exists
    if client.indices.exists(index=INDEX_NAME):
        print(f"Index '{INDEX_NAME}' already exists — skipping creation.")
        mapping = client.indices.get_mapping(index=INDEX_NAME)
        print(f"  Current mappings: {list(mapping[INDEX_NAME]['mappings']['properties'].keys())}")
        return 0

    # AC-3: index settings with BM25 (default similarity in OpenSearch) and custom analyzer
    index_body = {
        "settings": {
            "number_of_shards":   3,     # one primary shard per node
            "number_of_replicas": 1,     # one replica per shard — tolerates 1 node failure
            "similarity": {
                "default": {
                    "type": "BM25",
                    "b":    0.75,
                    "k1":   1.2,
                }
            },
            "analysis": {
                "analyzer": {
                    # AC-3: custom BM25-tuned analyzer
                    "contextiq_bm25": {
                        "type":      "custom",
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "stop",
                            "porter_stem",
                            "contextiq_length_filter",
                        ],
                    },
                    # Exact-match keyword analyzer for source_id and metadata fields
                    "contextiq_keyword": {
                        "type":      "custom",
                        "tokenizer": "keyword",
                        "filter":    ["lowercase"],
                    },
                },
                "filter": {
                    "contextiq_length_filter": {
                        "type":    "length",
                        "min":     2,
                        "max":     40,
                    }
                },
            },
        },
        "mappings": {
            # AC-3: explicit field mappings
            "properties": {
                "content": {
                    "type":     "text",
                    "analyzer": "contextiq_bm25",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    }
                },
                "source_id": {
                    "type":     "keyword",
                    "analyzer": "contextiq_keyword",
                },
                "metadata": {
                    "type":    "object",
                    "dynamic": True,     # allow arbitrary metadata sub-fields
                },
                "indexed_at": {
                    "type":   "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                # Supporting fields used by the agent retrieval pipeline
                "title": {
                    "type":     "text",
                    "analyzer": "contextiq_bm25",
                },
                "chunk_index": {
                    "type": "integer",
                },
                "connector_type": {
                    "type": "keyword",
                },
            }
        },
    }

    print(f"Creating index '{INDEX_NAME}'...")
    try:
        client.indices.create(index=INDEX_NAME, body=index_body)
    except RequestError as exc:
        if "resource_already_exists_exception" in str(exc):
            print(f"Index '{INDEX_NAME}' already exists (race condition) — OK.")
        else:
            print(f"ERROR creating index: {exc}", flush=True)
            return 1

    # Verify the index is green and the mapping is correct
    health = client.cluster.health(index=INDEX_NAME, wait_for_status="green", timeout="30s")
    print(f"Index '{INDEX_NAME}' created. Status: {health['status']}")

    mapping = client.indices.get_mapping(index=INDEX_NAME)
    fields = list(mapping[INDEX_NAME]["mappings"]["properties"].keys())
    for required_field in ("content", "source_id", "metadata", "indexed_at"):
        assert required_field in fields, f"Required field '{required_field}' missing from mapping"
        print(f"  [OK] field '{required_field}' present")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/opensearch.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: opensearch
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://opensearch-project.github.io/helm-charts
    chart:          opensearch
    targetRevision: "2.x.x"
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: false, selfHeal: true }
```

## Acceptance Criteria

- [ ] `kubectl get pods -n contextiq-data -l app.kubernetes.io/name=opensearch` shows 3 pods Running (AC-3)
- [ ] `curl -u admin:$PASS https://opensearch.contextiq-data.svc.cluster.local:9200/_cluster/health` shows `"status":"green","number_of_nodes":3` (AC-3)
- [ ] `bootstrap_opensearch.py` completes; `curl .../contextiq_documents/_mapping` shows `content`, `source_id`, `metadata`, `indexed_at` fields (AC-3)
- [ ] Index similarity is BM25: `curl .../contextiq_documents/_settings | jq '.["contextiq_documents"].settings.index.similarity'` shows `"type":"BM25"` (AC-3)
- [ ] `/vault/secrets/opensearch.env` present in pod with `OPENSEARCH_PASSWORD` set (AC-6)
- [ ] `kubectl get servicemonitor opensearch -n contextiq-observability` exists; Prometheus scrapes node metrics (AC-7)

## Dependencies

- TASK-US045-01 — `contextiq-data` namespace
- TASK-US047-02 — Vault `secret/contextiq/opensearch/admin` must exist (created via `rotate_static_secrets.sh` or operator bootstrap)
- TASK-US048-01 — cert-manager TLS certificates for OpenSearch inter-node transport TLS
- TASK-US048-04 — `contextiq-encrypted-gp3` StorageClass

## Definition of Done

- [ ] OpenSearch cluster green for 15 minutes with all 3 shards allocated
- [ ] `bootstrap_opensearch.py` committed and idempotent in staging
- [ ] Test document indexable: `PUT /contextiq_documents/_doc/1 {"content":"test","source_id":"s1","indexed_at":"2026-07-10T00:00:00Z","metadata":{}}` returns 201
