# TASK-US052-01 — Kafka KRaft 3-Broker StatefulSet Deployment

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US052-01 |
| User Story | US-052 |
| Epic | EP-DATA-002 — Event Streaming Infrastructure |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Deploy Apache Kafka 3.7.x in KRaft mode (no ZooKeeper) as a 3-broker `StatefulSet` in `contextiq-data` using the Bitnami `kafka` Helm chart (AC-1). All three brokers act as combined controller+broker nodes so the KRaft controller quorum is internal; a minimum of 2 nodes must agree to elect a new controller, tolerating one broker failure. Each broker has a dedicated `PersistentVolumeClaim` on `contextiq-encrypted-gp3` (AES-256 at rest). SCRAM-SHA-512 inter-broker authentication is configured; client credentials are Vault-injected via the Agent sidecar. A `PodDisruptionBudget` (minAvailable: 2) and `PodAntiAffinity` (requiredDuringScheduling on hostname) ensure HA.

## Implementation Details

**Technology:** Apache Kafka 3.7.x, Bitnami `kafka` Helm chart 29.x, KRaft mode, SCRAM-SHA-512

**File locations:**
- `helm/charts/kafka/Chart.yaml`
- `helm/charts/kafka/values.yaml`
- `helm/charts/kafka/values-prod.yaml`
- `argocd/apps/services/kafka.yaml`

---

### Helm wrapper

```yaml
# helm/charts/kafka/Chart.yaml
apiVersion: v2
name:        kafka
description: Apache Kafka KRaft cluster for ContextIQ event streaming
type:        application
version:     0.1.0
dependencies:
  - name:       kafka
    version:    "29.x.x"    # Bitnami chart tracking Kafka 3.7
    repository: https://charts.bitnami.com/bitnami
```

```yaml
# helm/charts/kafka/values.yaml
kafka:
  image:
    tag: "3.7.1-debian-12-r0"    # pin for reproducibility

  # AC-1: KRaft mode — no ZooKeeper
  kraft:
    enabled: true

  # AC-1: 3 brokers acting as combined controller+broker
  controller:
    replicaCount:         3
    controllerOnly:       false    # combined mode: each pod is both controller and broker
    minId:                0

    # Per-broker configuration
    config:
      # Replication factor for internal topics
      default.replication.factor:               "3"
      offsets.topic.replication.factor:         "3"
      transaction.state.log.replication.factor: "3"
      transaction.state.log.min.isr:            "2"
      min.insync.replicas:                      "2"    # require 2 ISR before ack (durability guarantee)

      # Log retention defaults (overridden per-topic during creation)
      log.retention.hours:             "168"     # 7 days
      log.segment.bytes:               "1073741824"  # 1 GB segment roll
      log.cleanup.policy:              "delete"

      # Performance
      num.network.threads:             "8"
      num.io.threads:                  "16"
      socket.send.buffer.bytes:        "102400"
      socket.receive.buffer.bytes:     "102400"
      socket.request.max.bytes:        "104857600"
      num.partitions:                  "6"      # default partition count

      # SCRAM-SHA-512 inter-broker auth (clients use SASL_SSL)
      sasl.mechanism.inter.broker.protocol: "SCRAM-SHA-512"
      sasl.enabled.mechanisms:              "SCRAM-SHA-512"
      security.inter.broker.protocol:      "SASL_SSL"
      listeners:           "SASL_SSL://:9092,CONTROLLER://:9093"
      advertised.listeners: "SASL_SSL://:9092"

    # Encrypted PVC (TASK-US048-04)
    persistence:
      enabled:      true
      storageClass: contextiq-encrypted-gp3
      size:         100Gi

    resources:
      requests: { cpu: "1",    memory: "4Gi" }
      limits:   { cpu: "4",    memory: "8Gi" }

    # AC-1: spread brokers across distinct K8s nodes
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app.kubernetes.io/name:      kafka
                app.kubernetes.io/component: controller
            topologyKey: kubernetes.io/hostname

    # Vault Agent injects SASL credentials at pod startup
    podAnnotations:
      vault.hashicorp.com/agent-inject:                 "true"
      vault.hashicorp.com/role:                         "mcp-gateway"
      vault.hashicorp.com/agent-pre-populate-only:      "true"
      vault.hashicorp.com/agent-inject-secret-kafka:    "secret/data/contextiq/kafka/broker"
      vault.hashicorp.com/agent-inject-template-kafka: |
        {{- with secret "secret/data/contextiq/kafka/broker" -}}
        export KAFKA_INTER_BROKER_USER="{{ .Data.data.username }}"
        export KAFKA_INTER_BROKER_PASSWORD="{{ .Data.data.password }}"
        {{- end }}

  # JVM heap: 4 GB for 8 GB node (50% rule)
  heapOpts: "-Xmx4G -Xms4G"

  # PDB — AC-1: tolerate 1 broker failure while maintaining quorum (2 of 3)
  podDisruptionBudget:
    enabled:      true
    minAvailable: 2

  # TLS for client connections (cert-manager certificate, TASK-US048-01)
  tls:
    enabled:    true
    existingSecrets:
      - name: kafka-tls    # cert-manager Certificate
        certificateKey: tls.crt
        privateKeyKey:  tls.key
        chainKey:       ca.crt

  # Client credentials for application services
  sasl:
    client:
      users:
        - name:     mcp-gateway
          password: ""    # overwritten by Vault Agent
        - name:     indexing-service
          password: ""
        - name:     agent-worker
          password: ""
        - name:     admin-api
          password: ""
```

```yaml
# helm/charts/kafka/values-prod.yaml
kafka:
  controller:
    persistence:
      size: 500Gi
    resources:
      requests: { cpu: "4",  memory: "16Gi" }
      limits:   { cpu: "8",  memory: "32Gi" }
  heapOpts: "-Xmx12G -Xms12G"
```

---

### Vault secret bootstrap for Kafka credentials

```bash
#!/usr/bin/env bash
# scripts/vault/configure_kafka_secrets.sh
# Store Kafka broker inter-broker credentials and per-service client credentials in Vault KV v2.
# Run once during initial Vault setup (TASK-US047-02 extension).
set -euo pipefail

echo "=== Configuring Kafka secrets in Vault ==="

# Inter-broker credentials
vault kv put secret/contextiq/kafka/broker \
  username="kafka-inter-broker" \
  password="${KAFKA_INTER_BROKER_PASSWORD:?KAFKA_INTER_BROKER_PASSWORD required}"

# Per-service client credentials
for SVC in mcp-gateway indexing-service agent-worker admin-api; do
  vault kv put "secret/contextiq/kafka/clients/${SVC}" \
    username="${SVC}" \
    password="${SVC}_$(openssl rand -hex 16)"
  echo "  Client credentials stored for $SVC"
done

echo "=== Kafka secrets configured ==="
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/kafka.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kafka
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://charts.bitnami.com/bitnami
    chart:          kafka
    targetRevision: "29.x.x"
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: false, selfHeal: true }
    # prune: false — PVCs with broker data must not be deleted automatically
```

## Acceptance Criteria

- [ ] `kubectl get pods -n contextiq-data -l app.kubernetes.io/name=kafka` shows 3 Running pods (AC-1)
- [ ] `kubectl exec -n contextiq-data kafka-controller-0 -- kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status` shows `LeaderId` set and `CurrentVoters` has 3 entries (AC-1 KRaft quorum)
- [ ] No ZooKeeper pods running in `contextiq-data` namespace — KRaft confirmed (AC-1)
- [ ] `kubectl get pvc -n contextiq-data -l app.kubernetes.io/name=kafka` shows 3 PVCs bound with `contextiq-encrypted-gp3` (AC-1)
- [ ] `kubectl get pdb kafka-controller -n contextiq-data` shows `ALLOWED-DISRUPTIONS: 1` (AC-1 HA)
- [ ] Each broker pod has `/vault/secrets/kafka.env` with `KAFKA_INTER_BROKER_PASSWORD` set (Vault injection)

## Dependencies

- TASK-US045-01 — `contextiq-data` namespace must exist
- TASK-US047-02 — Vault `secret/contextiq/kafka/broker` KV path must exist (run `configure_kafka_secrets.sh`)
- TASK-US048-01 — `kafka-tls` cert-manager Certificate must exist for TLS listener
- TASK-US048-04 — `contextiq-encrypted-gp3` StorageClass must exist

## Definition of Done

- [ ] `helm install kafka bitnami/kafka -n contextiq-data -f values.yaml -f values-prod.yaml` completes with all 3 pods Running
- [ ] KRaft quorum describe shows 3 voters and an active leader
- [ ] `kafka-topics.sh --bootstrap-server kafka.contextiq-data.svc.cluster.local:9092 --list` executable (prereq for TASK-US052-02)
