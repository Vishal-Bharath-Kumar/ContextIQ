# TASK-US052-04 — Kafka Connect Deployment and Prometheus Broker Metrics

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US052-04 |
| User Story | US-052 |
| Epic | EP-DATA-002 — Event Streaming Infrastructure |
| Layer | Infrastructure / Observability |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Deploy Kafka Connect as a 2-replica `Deployment` alongside the Kafka cluster (AC-4). Kafka Connect is deployed in distributed mode with its internal offset/config/status topics using the `contextiq-data` cluster, ready for future source/sink connectors without needing cluster recreation. Prometheus metrics for broker lag, throughput, and under-replicated partitions are scraped via the Kafka JMX Exporter sidecar on each broker and a `ServiceMonitor` targeting `contextiq-observability` (AC-5). A pre-built Grafana dashboard JSON is committed for importing.

## Implementation Details

**Technology:** Kafka Connect 3.7.x (Confluent or Bitnami image), JMX Exporter 0.20, Prometheus ServiceMonitor, Grafana dashboard JSON

**File locations:**
- `helm/charts/kafka-connect/Chart.yaml`
- `helm/charts/kafka-connect/values.yaml`
- `k8s/kafka/jmx-configmap.yaml` — JMX Exporter rules for broker metrics
- `k8s/kafka/servicemonitor.yaml` — Prometheus scrape target
- `k8s/observability/dashboards/kafka.json` — Grafana dashboard
- `argocd/apps/services/kafka-connect.yaml`

---

### Kafka Connect Helm wrapper

```yaml
# helm/charts/kafka-connect/Chart.yaml
apiVersion: v2
name:        kafka-connect
description: Kafka Connect distributed mode for ContextIQ data pipelines
type:        application
version:     0.1.0
dependencies:
  - name:       kafka-connect
    version:    "1.x.x"    # Bitnami kafka (includes Connect in distributed mode)
    repository: https://charts.bitnami.com/bitnami
```

```yaml
# helm/charts/kafka-connect/values.yaml
kafka-connect:
  image:
    # Use the same Kafka image for version alignment
    tag: "3.7.1-debian-12-r0"

  # AC-4: distributed mode, 2 replicas for HA
  replicaCount: 2

  # Connect internal topics — must match cluster replication factor
  config:
    group.id:                             "contextiq-connect"
    config.storage.topic:                 "_connect-configs"
    offset.storage.topic:                 "_connect-offsets"
    status.storage.topic:                 "_connect-status"
    config.storage.replication.factor:    "3"
    offset.storage.replication.factor:    "3"
    status.storage.replication.factor:    "3"
    offset.storage.partitions:            "25"
    key.converter:                        "org.apache.kafka.connect.json.JsonConverter"
    value.converter:                      "org.apache.kafka.connect.json.JsonConverter"
    key.converter.schemas.enable:         "false"
    value.converter.schemas.enable:       "false"
    # SCRAM-SHA-512 for Connect → broker connection
    security.protocol:                    "SASL_SSL"
    sasl.mechanism:                       "SCRAM-SHA-512"
    producer.security.protocol:           "SASL_SSL"
    producer.sasl.mechanism:              "SCRAM-SHA-512"
    consumer.security.protocol:           "SASL_SSL"
    consumer.sasl.mechanism:              "SCRAM-SHA-512"

  # Bootstrap server — points at the Kafka StatefulSet headless service
  externalKafka:
    brokers: "kafka.contextiq-data.svc.cluster.local:9092"

  # Vault Agent injects SASL credentials
  podAnnotations:
    vault.hashicorp.com/agent-inject:                     "true"
    vault.hashicorp.com/role:                             "mcp-gateway"
    vault.hashicorp.com/agent-pre-populate-only:          "true"
    vault.hashicorp.com/agent-inject-secret-kafka:        "secret/data/contextiq/kafka/clients/mcp-gateway"
    vault.hashicorp.com/agent-inject-template-kafka: |
      {{- with secret "secret/data/contextiq/kafka/clients/mcp-gateway" -}}
      export KAFKA_CONNECT_SASL_USERNAME="{{ .Data.data.username }}"
      export KAFKA_CONNECT_SASL_PASSWORD="{{ .Data.data.password }}"
      {{- end }}

  # REST API for connector lifecycle management (not exposed externally)
  service:
    type:       ClusterIP
    port:       8083
    targetPort: 8083

  # AC-5: expose JMX metrics port for the JMX Exporter sidecar
  jmx:
    enabled: true
    port:    9999

  resources:
    requests: { cpu: "500m", memory: "1Gi" }
    limits:   { cpu: "2",    memory: "4Gi" }

  # REST listener NetworkPolicy — only allow calls from within contextiq-data
  networkPolicy:
    enabled:        true
    allowExternal:  false
```

---

### JMX Exporter configuration

```yaml
# k8s/kafka/jmx-configmap.yaml
# AC-5: Prometheus-compatible JMX Exporter rules for key Kafka broker metrics.
# Mounted as a ConfigMap sidecar on each broker pod.
apiVersion: v1
kind: ConfigMap
metadata:
  name: kafka-jmx-config
  namespace: contextiq-data
data:
  jmx-kafka-prometheus.yml: |
    startDelaySeconds: 30
    ssl: false
    lowercaseOutputName: true
    lowercaseOutputLabelNames: true

    rules:
      # --- Under-replicated partitions (AC-5: alert threshold > 0) ---
      - pattern: "kafka.server<type=ReplicaManager, name=UnderReplicatedPartitions><>Value"
        name:    kafka_server_replicamanager_underreplicatedpartitions
        labels:  { broker_id: "$1" }

      # --- Consumer lag (AC-5: key operational metric) ---
      - pattern: "kafka.consumer<type=consumer-fetch-manager-metrics, client-id=(.+)><>records-lag-max"
        name:    kafka_consumer_fetch_manager_records_lag_max
        labels:  { client_id: "$1" }

      # --- Broker bytes in/out per topic (throughput) ---
      - pattern: "kafka.server<type=BrokerTopicMetrics, name=BytesInPerSec, topic=(.+)><>OneMinuteRate"
        name:    kafka_server_brokertopicmetrics_bytesin_rate
        labels:  { topic: "$1" }
      - pattern: "kafka.server<type=BrokerTopicMetrics, name=BytesOutPerSec, topic=(.+)><>OneMinuteRate"
        name:    kafka_server_brokertopicmetrics_bytesout_rate
        labels:  { topic: "$1" }

      # --- Messages in per second per topic ---
      - pattern: "kafka.server<type=BrokerTopicMetrics, name=MessagesInPerSec, topic=(.+)><>OneMinuteRate"
        name:    kafka_server_brokertopicmetrics_messagesin_rate
        labels:  { topic: "$1" }

      # --- Request rate ---
      - pattern: "kafka.network<type=RequestMetrics, name=RequestsPerSec, request=(.+)><>OneMinuteRate"
        name:    kafka_network_requestmetrics_requestspersec_rate
        labels:  { request: "$1" }

      # --- ISR shrink/expand (leading indicator for replication health) ---
      - pattern: "kafka.server<type=ReplicaManager, name=IsrShrinksPerSec><>OneMinuteRate"
        name:    kafka_server_replicamanager_isrshrinks_rate
      - pattern: "kafka.server<type=ReplicaManager, name=IsrExpandsPerSec><>OneMinuteRate"
        name:    kafka_server_replicamanager_isrexpands_rate

      # --- Active controller count (should be exactly 1 cluster-wide) ---
      - pattern: "kafka.controller<type=KafkaController, name=ActiveControllerCount><>Value"
        name:    kafka_controller_kafkacontroller_activecontrollercount

      # --- Offline partitions (should be 0 at all times) ---
      - pattern: "kafka.controller<type=KafkaController, name=OfflinePartitionsCount><>Value"
        name:    kafka_controller_kafkacontroller_offlinepartitionscount
```

---

### Prometheus ServiceMonitor

```yaml
# k8s/kafka/servicemonitor.yaml
# AC-5: Prometheus scrapes Kafka broker JMX metrics every 30s.
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name:      kafka
  namespace: contextiq-observability
  labels:
    app.kubernetes.io/part-of: contextiq
spec:
  namespaceSelector:
    matchNames: [contextiq-data]
  selector:
    matchLabels:
      app.kubernetes.io/name:      kafka
      app.kubernetes.io/component: controller    # target broker pods
  endpoints:
    - port:     jmx-exporter    # 9308 on broker pods
      interval: 30s
      path:     /metrics
```

---

### Kafka consumer-lag recording rule (Prometheus)

```yaml
# k8s/observability/rules/kafka-consumer-lag.yaml
# AC-5: Derived consumer-lag metric — used by Grafana dashboard and alerts.
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name:      kafka-consumer-lag
  namespace: contextiq-observability
spec:
  groups:
    - name: kafka.consumer_lag
      interval: 30s
      rules:
        - record: kafka:consumer_group_lag:max_by_topic
          expr: |
            max by (topic, group, namespace) (
              kafka_consumergroup_lag{namespace="contextiq-data"}
            )
        - alert: KafkaConsumerLagHigh
          expr: kafka:consumer_group_lag:max_by_topic > 10000
          for: 5m
          labels:    { severity: warning }
          annotations:
            summary:     "Consumer group {{ $labels.group }} lag > 10k on {{ $labels.topic }}"
            description: "Lag is {{ $value }} messages — check consumer pod health."
        - alert: KafkaUnderReplicatedPartitions
          expr: kafka_server_replicamanager_underreplicatedpartitions > 0
          for: 2m
          labels:    { severity: critical }
          annotations:
            summary:     "Kafka under-replicated partitions detected"
            description: "{{ $value }} partitions are under-replicated — broker may be down."
```

---

### ArgoCD Application for Kafka Connect

```yaml
# argocd/apps/services/kafka-connect.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kafka-connect
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://charts.bitnami.com/bitnami
    chart:          kafka
    targetRevision: "29.x.x"
    helm:
      valueFiles: [values.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

## Acceptance Criteria

- [ ] `kubectl get pods -n contextiq-data -l app.kubernetes.io/name=kafka-connect` shows 2 Running pods (AC-4)
- [ ] `curl http://kafka-connect.contextiq-data.svc.cluster.local:8083/connectors` returns `[]` (empty list — no connectors yet, but REST API is responsive) (AC-4)
- [ ] `curl http://kafka-connect.contextiq-data.svc.cluster.local:8083/` returns Kafka Connect version JSON (AC-4)
- [ ] `kubectl get servicemonitor kafka -n contextiq-observability` exists (AC-5)
- [ ] `curl http://prometheus.contextiq-observability.svc.cluster.local:9090/api/v1/query?query=kafka_server_replicamanager_underreplicatedpartitions` returns a value of `0` for all brokers (AC-5)
- [ ] `kafka_controller_kafkacontroller_activecontrollercount` metric equals `1` in Prometheus (AC-5)
- [ ] `kafka_server_brokertopicmetrics_bytesin_rate` metric is present for all 6 topics in Prometheus (AC-5)
- [ ] Grafana dashboard `k8s/observability/dashboards/kafka.json` importable and renders consumer-lag panels (AC-5)

## Dependencies

- TASK-US052-01 — Kafka brokers running (Kafka Connect needs the cluster to register its internal topics)
- TASK-US052-02 — Topics created (Kafka Connect internal `_connect-*` topics need `replication.factor=3`)
- TASK-US047-02 — Vault `secret/contextiq/kafka/clients/mcp-gateway` for Connect SASL credentials
- Prometheus Operator deployed (US-046) — for ServiceMonitor CRD

## Definition of Done

- [ ] Kafka Connect REST API responding on port 8083 with 2 running pods
- [ ] All 8 JMX metrics visible in Prometheus UI
- [ ] `KafkaUnderReplicatedPartitions` alert rule present in Prometheus
- [ ] Grafana dashboard committed and importable in staging
