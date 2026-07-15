# TASK-US052-02 — Kafka Topic Creation with Partition and Retention Settings

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US052-02 |
| User Story | US-052 |
| Epic | EP-DATA-002 — Event Streaming Infrastructure |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Create all 6 required Kafka topics with their specified partition counts, retention periods, and replication settings (AC-2). Topics are provisioned by a Python script that is also run as a Kubernetes `Job` annotated as an ArgoCD pre-sync hook — so topics exist before any producer or consumer pods start on each deployment. The script is idempotent: it skips topic creation if a topic already exists and validates that existing topics have the correct configuration, emitting a warning if settings drift. Each topic uses `replication.factor=3` and `min.insync.replicas=2` for durability on the 3-broker cluster.

## Implementation Details

**Technology:** `aiokafka>=0.11`, `kafka-python>=2.0`, Kubernetes `Job`

**File locations:**
- `scripts/kafka/bootstrap_topics.py` — topic creation + validation script
- `k8s/kafka/topic-bootstrap-job.yaml` — ArgoCD pre-sync Job
- `src/kafka/topic_registry.py` — canonical topic definitions shared by producers and consumers

---

### Canonical topic registry

```python
# src/kafka/topic_registry.py
"""
Single source of truth for all Kafka topic names, partition counts, and retention.
Imported by bootstrap_topics.py (provisioning) and by producer/consumer code (validation).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicSpec:
    name:              str
    partitions:        int
    replication_factor: int
    retention_ms:      int     # -1 = unlimited
    cleanup_policy:    str = "delete"
    consumer_groups:   tuple[str, ...] = ()


# AC-2: canonical topic table
TOPICS: list[TopicSpec] = [
    TopicSpec(
        name="knowledge.source.synced",
        partitions=6,
        replication_factor=3,
        retention_ms=7 * 24 * 60 * 60 * 1000,    # 7 days
        consumer_groups=("indexing-service",),
    ),
    TopicSpec(
        name="knowledge.chunk.indexed",
        partitions=12,
        replication_factor=3,
        retention_ms=7 * 24 * 60 * 60 * 1000,    # 7 days
        consumer_groups=("graph-agent",),
    ),
    TopicSpec(
        name="knowledge.graph.updated",
        partitions=6,
        replication_factor=3,
        retention_ms=7 * 24 * 60 * 60 * 1000,    # 7 days
        consumer_groups=("context-retrieval",),
    ),
    TopicSpec(
        name="contextiq.state.events",
        partitions=12,
        replication_factor=3,
        retention_ms=24 * 60 * 60 * 1000,         # 24 hours
        consumer_groups=("replay-service",),
    ),
    TopicSpec(
        name="contextiq.governance.events",
        partitions=6,
        replication_factor=3,
        retention_ms=30 * 24 * 60 * 60 * 1000,   # 30 days
        consumer_groups=("audit-logger",),
    ),
    TopicSpec(
        name="contextiq.connector.health",
        partitions=3,
        replication_factor=3,
        retention_ms=60 * 60 * 1000,              # 1 hour
        consumer_groups=("health-monitor",),
    ),
]

# Lookup by topic name
TOPIC_MAP: dict[str, TopicSpec] = {t.name: t for t in TOPICS}
```

---

### Topic bootstrap script

```python
# scripts/kafka/bootstrap_topics.py
"""
AC-2: Create all Kafka topics with specified partition and retention settings.
Idempotent — skips existing topics, warns on config drift.
Run as a Kubernetes Job (ArgoCD pre-sync hook) before any consumer/producer starts.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, NoBrokersAvailable

from src.kafka.topic_registry import TOPICS, TopicSpec


BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.contextiq-data.svc.cluster.local:9092",
)
KAFKA_USERNAME = os.environ.get("KAFKA_USERNAME", "")
KAFKA_PASSWORD = os.environ.get("KAFKA_PASSWORD", "")

MAX_RETRIES    = 10
RETRY_DELAY_S  = 6


def _log(event: str, **kwargs: Any) -> None:
    print(json.dumps({"event": event, **kwargs}), flush=True)


def _make_admin() -> KafkaAdminClient:
    """Create a KafkaAdminClient with SCRAM-SHA-512 auth and retry on NoBrokersAvailable."""
    kwargs: dict[str, Any] = {
        "bootstrap_servers": BOOTSTRAP_SERVERS,
        "client_id":         "topic-bootstrap",
        "security_protocol": "SASL_SSL",
        "sasl_mechanism":    "SCRAM-SHA-512",
        "sasl_plain_username": KAFKA_USERNAME,
        "sasl_plain_password": KAFKA_PASSWORD,
        "ssl_cafile":        "/tls/ca.crt",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return KafkaAdminClient(**kwargs)
        except NoBrokersAvailable:
            _log("kafka_not_ready", attempt=attempt, retry_in_s=RETRY_DELAY_S)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_DELAY_S)
    raise RuntimeError("unreachable")


def _retention_config(spec: TopicSpec) -> dict[str, str]:
    return {
        "retention.ms":        str(spec.retention_ms),
        "cleanup.policy":      spec.cleanup_policy,
        "min.insync.replicas": "2",    # durability: require 2 of 3 brokers to ack
        "compression.type":    "lz4",  # compress all topics for bandwidth efficiency
    }


def main() -> int:
    _log("topic_bootstrap_start", topics=[t.name for t in TOPICS])

    admin = _make_admin()

    # Fetch existing topics and their configs
    existing_topics: set[str] = set(admin.list_topics())
    _log("existing_topics", count=len(existing_topics), topics=sorted(existing_topics))

    to_create: list[NewTopic] = []
    for spec in TOPICS:
        if spec.name in existing_topics:
            _log("topic_already_exists", topic=spec.name)
            # Validate existing topic partition count (cannot be reduced)
            meta = admin.describe_topics([spec.name])
            actual_partitions = len(meta[0]["partitions"])
            if actual_partitions != spec.partitions:
                _log(
                    "topic_partition_drift",
                    topic=spec.name,
                    expected=spec.partitions,
                    actual=actual_partitions,
                    level="WARNING",
                )
                # Increase partitions if the actual count is lower than specified
                if actual_partitions < spec.partitions:
                    _log("topic_increasing_partitions", topic=spec.name, new_count=spec.partitions)
                    admin.create_partitions({spec.name: spec.partitions})
        else:
            to_create.append(
                NewTopic(
                    name=spec.name,
                    num_partitions=spec.partitions,
                    replication_factor=spec.replication_factor,
                    topic_configs=_retention_config(spec),
                )
            )

    if to_create:
        _log("creating_topics", count=len(to_create), names=[t.name for t in to_create])
        try:
            admin.create_topics(new_topics=to_create, validate_only=False)
        except TopicAlreadyExistsError:
            _log("some_topics_already_exist_race_condition", level="WARNING")

    # Apply/update retention configs for all topics (idempotent alter_configs)
    config_updates = {
        spec.name: _retention_config(spec)
        for spec in TOPICS
        if spec.name in existing_topics    # only alter pre-existing topics
    }
    if config_updates:
        admin.alter_configs(config_updates)
        _log("retention_configs_applied", topic_count=len(config_updates))

    # Final verification
    final_topics = set(admin.list_topics())
    missing = [spec.name for spec in TOPICS if spec.name not in final_topics]
    if missing:
        _log("topic_bootstrap_failed", missing_topics=missing)
        admin.close()
        return 1

    _log("topic_bootstrap_complete", total_topics=len(TOPICS))
    admin.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### Kubernetes pre-sync Job

```yaml
# k8s/kafka/topic-bootstrap-job.yaml
# ArgoCD pre-sync hook: topics must exist before consumer/producer pods start.
apiVersion: batch/v1
kind: Job
metadata:
  name: kafka-topic-bootstrap
  namespace: contextiq-data
  annotations:
    argocd.argoproj.io/hook:               PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit:          2    # retry up to 2 times on transient broker unavailability
  activeDeadlineSeconds: 180
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject:                  "true"
        vault.hashicorp.com/role:                          "mcp-gateway"
        vault.hashicorp.com/agent-pre-populate-only:       "true"
        vault.hashicorp.com/agent-inject-secret-kafka:     "secret/data/contextiq/kafka/clients/mcp-gateway"
        vault.hashicorp.com/agent-inject-template-kafka: |
          {{- with secret "secret/data/contextiq/kafka/clients/mcp-gateway" -}}
          export KAFKA_USERNAME="{{ .Data.data.username }}"
          export KAFKA_PASSWORD="{{ .Data.data.password }}"
          {{- end }}
    spec:
      restartPolicy: OnFailure
      serviceAccountName: kafka-bootstrap
      containers:
        - name: bootstrap
          image: ghcr.io/org/contextiq-api:$(IMAGE_TAG)
          command: ["/bin/sh", "-c"]
          args:
            - |
              . /vault/secrets/kafka.env
              python scripts/kafka/bootstrap_topics.py
          env:
            - name: KAFKA_BOOTSTRAP_SERVERS
              value: kafka.contextiq-data.svc.cluster.local:9092
          volumeMounts:
            - name: kafka-tls
              mountPath: /tls
              readOnly: true
          resources:
            requests: { cpu: "100m", memory: "128Mi" }
            limits:   { cpu: "500m", memory: "256Mi" }
      volumes:
        - name: kafka-tls
          secret:
            secretName: kafka-tls    # cert-manager Certificate (TASK-US048-01)
```

## Acceptance Criteria

- [x] `kafka-topics.sh --list` shows all 6 topic names (AC-2)
- [x] `kafka-topics.sh --describe --topic knowledge.chunk.indexed` shows `PartitionCount: 12`, `ReplicationFactor: 3`, `retention.ms: 604800000` (7 days) (AC-2)
- [x] `kafka-topics.sh --describe --topic contextiq.state.events` shows `retention.ms: 86400000` (24 hours) (AC-2)
- [x] `kafka-topics.sh --describe --topic contextiq.connector.health` shows `PartitionCount: 3`, `retention.ms: 3600000` (1 hour) (AC-2)
- [x] All topics have `min.insync.replicas=2` (AC-2)
- [x] `bootstrap_topics.py` runs idempotently — running twice does not error or change topic config (AC-2)
- [x] ArgoCD pre-sync Job `kafka-topic-bootstrap` exits 0 before any consumer pods start (AC-2)

## Dependencies

- TASK-US052-01 — Kafka brokers must be Running with SCRAM-SHA-512 auth before topic creation
- `src/kafka/topic_registry.py` committed so the registry is importable from the `contextiq-api` image
- `KAFKA_USERNAME` / `KAFKA_PASSWORD` Vault secrets populated by `configure_kafka_secrets.sh` (TASK-US052-01)

## Definition of Done

- [x] `bootstrap_topics.py` committed; passes `python scripts/kafka/bootstrap_topics.py` in a test pod
- [x] All 6 topics visible in a Kafka UI tool (e.g. Kafdrop or kafka-ui)
- [x] `k8s/kafka/topic-bootstrap-job.yaml` committed; ArgoCD pre-sync hook recognised
