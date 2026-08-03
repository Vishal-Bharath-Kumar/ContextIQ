# TASK-US052-03 — Consumer Group Pre-registration and Startup Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US052-03 |
| User Story | US-052 |
| Epic | EP-DATA-002 — Event Streaming Infrastructure |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Pre-register all 6 consumer groups (`indexing-service`, `graph-agent`, `context-retrieval`, `replay-service`, `audit-logger`, `health-monitor`) so that broker-side offset tracking and partition assignment are ready before the first message is consumed (AC-3). A FastAPI lifespan startup hook in each consumer service validates that its consumer group exists and its assigned topics have the expected partition count, failing fast with a descriptive error if the broker is unreachable or the topic is missing. A reusable `KafkaConsumerValidator` class is shared across all services via `src/kafka/consumer_validator.py`.

## Implementation Details

**Technology:** `aiokafka>=0.11`, Python 3.11+, FastAPI lifespan

**File locations:**
- `scripts/kafka/register_consumer_groups.py` — pre-registration script (run as K8s Job alongside topic bootstrap)
- `src/kafka/consumer_validator.py` — startup validation mixin used by all services
- `src/kafka/consumer_base.py` — base `AIOKafkaConsumer` wrapper with auto-commit and error handling
- `k8s/kafka/consumer-group-job.yaml` — ArgoCD pre-sync Job (runs after topic bootstrap)

---

### Consumer group pre-registration script

```python
# scripts/kafka/register_consumer_groups.py
"""
AC-3: Pre-register all consumer groups by performing a single dummy consume
with auto_offset_reset='latest'. This creates the group metadata on the broker
without consuming any actual messages, so offset tracking starts from 'now'.

Idempotent — groups that already have committed offsets are left unchanged.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import UnknownTopicOrPartitionError

from src.kafka.topic_registry import TOPICS, TOPIC_MAP

BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.contextiq-data.svc.cluster.local:9092",
)
KAFKA_USERNAME = os.environ.get("KAFKA_USERNAME", "")
KAFKA_PASSWORD = os.environ.get("KAFKA_PASSWORD", "")


def _log(event: str, **kwargs: Any) -> None:
    print(json.dumps({"event": event, **kwargs}), flush=True)


def _sasl_kwargs() -> dict[str, Any]:
    return {
        "security_protocol":   "SASL_SSL",
        "sasl_mechanism":      "SCRAM-SHA-512",
        "sasl_plain_username": KAFKA_USERNAME,
        "sasl_plain_password": KAFKA_PASSWORD,
        "ssl_cafile":          "/tls/ca.crt",
    }


async def register_group(group_id: str, topics: list[str]) -> bool:
    """
    Create a consumer group on the broker by subscribing and immediately closing.
    Uses auto_offset_reset='latest' so the group starts consuming future messages only.
    """
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=group_id,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        consumer_timeout_ms=1000,    # don't wait for messages — just register
        **_sasl_kwargs(),
    )
    try:
        await consumer.start()
        # Fetch assignment metadata — this triggers group join and partition assignment
        assignment = consumer.assignment()
        _log(
            "consumer_group_registered",
            group_id=group_id,
            topics=topics,
            partitions_assigned=len(assignment),
        )
        return True
    except UnknownTopicOrPartitionError as exc:
        _log("consumer_group_registration_failed", group_id=group_id, error=str(exc))
        return False
    finally:
        await consumer.stop()


async def main() -> int:
    if not KAFKA_USERNAME:
        _log("error", message="KAFKA_USERNAME not set")
        return 1

    # Build group → topics mapping from the topic registry
    group_topics: dict[str, list[str]] = {}
    for spec in TOPICS:
        for group in spec.consumer_groups:
            group_topics.setdefault(group, []).append(spec.name)

    _log("registering_consumer_groups", groups=list(group_topics.keys()))

    results = await asyncio.gather(
        *[register_group(group, topics) for group, topics in group_topics.items()],
        return_exceptions=True,
    )

    failures = [
        group
        for group, result in zip(group_topics.keys(), results)
        if result is not True
    ]

    if failures:
        _log("consumer_group_registration_partial_failure", failed_groups=failures)
        return 1

    _log("consumer_group_registration_complete", total_groups=len(group_topics))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

---

### Reusable startup validator

```python
# src/kafka/consumer_validator.py
"""
AC-3: Startup validation — asserts that consumer group and topics exist on the broker
before the service starts processing. Used in FastAPI lifespan hooks.
"""
from __future__ import annotations

import logging
from typing import Any

from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import UnknownTopicOrPartitionError

from src.kafka.topic_registry import TOPIC_MAP, TopicSpec

logger = logging.getLogger(__name__)


class KafkaConsumerValidator:
    """
    Validates Kafka topics and consumer group membership at service startup.
    Raise RuntimeError if validation fails — this surfaces as a pod startup failure (AC-3).
    """

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topic_names: list[str],
        sasl_kwargs: dict[str, Any],
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topic_names = topic_names
        self._sasl_kwargs = sasl_kwargs

    async def validate(self) -> None:
        """
        Connect to Kafka and assert:
          1. All required topics exist with the expected partition count (AC-3)
          2. Consumer group has been pre-registered (AC-3)
        """
        admin = AIOKafkaAdminClient(
            bootstrap_servers=self._bootstrap_servers,
            client_id=f"startup-validator-{self._group_id}",
            **self._sasl_kwargs,
        )
        await admin.start()
        try:
            # 1. Check topics exist with correct partition count
            topic_meta = await admin.describe_topics(self._topic_names)
            for meta in topic_meta:
                topic_name = meta["topic"]
                if meta.get("error_code", 0) != 0:
                    raise RuntimeError(
                        f"Kafka topic '{topic_name}' not found or has error "
                        f"(code={meta['error_code']}). "
                        f"Run kafka topic bootstrap before starting this service."
                    )
                spec: TopicSpec | None = TOPIC_MAP.get(topic_name)
                if spec and len(meta["partitions"]) != spec.partitions:
                    raise RuntimeError(
                        f"Kafka topic '{topic_name}' has {len(meta['partitions'])} partitions, "
                        f"expected {spec.partitions}. Topic may need manual repair."
                    )
                logger.info(
                    "kafka_topic_validated",
                    extra={"topic": topic_name, "partitions": len(meta["partitions"])},
                )

            # 2. Check that the consumer group exists (was pre-registered by TASK-US052-03 job)
            group_descriptions = await admin.describe_consumer_groups([self._group_id])
            group = next((g for g in group_descriptions if g.group_id == self._group_id), None)
            if group is None:
                raise RuntimeError(
                    f"Consumer group '{self._group_id}' not found on broker. "
                    f"Run consumer group pre-registration job before deploying this service."
                )
            logger.info("kafka_consumer_group_validated", extra={"group_id": self._group_id})

        finally:
            await admin.close()
```

---

### Base consumer with auto-commit and error handling

```python
# src/kafka/consumer_base.py
"""
Base AIOKafka consumer wrapper.
Each service subclasses this and implements process_message().
"""
from __future__ import annotations

import asyncio
import logging
import os
from abc import abstractmethod
from typing import Any

from aiokafka import AIOKafkaConsumer, ConsumerRecord

from src.kafka.consumer_validator import KafkaConsumerValidator

logger = logging.getLogger(__name__)

BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.contextiq-data.svc.cluster.local:9092",
)


def _sasl_kwargs() -> dict[str, Any]:
    return {
        "security_protocol":   "SASL_SSL",
        "sasl_mechanism":      "SCRAM-SHA-512",
        "sasl_plain_username": os.environ.get("KAFKA_USERNAME", ""),
        "sasl_plain_password": os.environ.get("KAFKA_PASSWORD", ""),
        "ssl_cafile":          "/tls/ca.crt",
    }


class BaseKafkaConsumer:
    """
    Reusable Kafka consumer base.
    Usage:
        class IndexingConsumer(BaseKafkaConsumer):
            topic_names = ["knowledge.source.synced"]
            group_id    = "indexing-service"

            async def process_message(self, record: ConsumerRecord) -> None:
                ...
    """
    topic_names: list[str] = []
    group_id: str = ""

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self) -> None:
        """Validate topics + group, then start consuming. Called from FastAPI lifespan."""
        validator = KafkaConsumerValidator(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            group_id=self.group_id,
            topic_names=self.topic_names,
            sasl_kwargs=_sasl_kwargs(),
        )
        # AC-3: raises RuntimeError if topics or group are missing — surfaces as startup failure
        await validator.validate()

        self._consumer = AIOKafkaConsumer(
            *self.topic_names,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=False,    # manual commit after successful processing
            **_sasl_kwargs(),
        )
        await self._consumer.start()
        asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        if self._consumer:
            await self._consumer.stop()

    async def _consume_loop(self) -> None:
        assert self._consumer is not None
        async for record in self._consumer:
            try:
                await self.process_message(record)
                await self._consumer.commit()
            except Exception as exc:
                logger.error(
                    "kafka_message_processing_error",
                    extra={
                        "topic":     record.topic,
                        "partition": record.partition,
                        "offset":    record.offset,
                        "error":     str(exc),
                    },
                    exc_info=True,
                )
                # Do NOT commit on failure — message will be re-delivered on restart

    @abstractmethod
    async def process_message(self, record: ConsumerRecord) -> None:
        """Implement in each service to handle a single Kafka message."""
```

---

### Kubernetes pre-sync Job for consumer group registration

```yaml
# k8s/kafka/consumer-group-job.yaml
# AC-3: ArgoCD pre-sync hook — runs after topic bootstrap, before consumer pods start.
apiVersion: batch/v1
kind: Job
metadata:
  name: kafka-consumer-group-registration
  namespace: contextiq-data
  annotations:
    argocd.argoproj.io/hook:               PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
    # This hook must run AFTER topic bootstrap (weight -4 vs -5 for topic bootstrap)
    argocd.argoproj.io/sync-wave:          "-4"
spec:
  backoffLimit:          2
  activeDeadlineSeconds: 120
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
        - name: register-groups
          image: ghcr.io/org/contextiq-api:$(IMAGE_TAG)
          command: ["/bin/sh", "-c"]
          args:
            - |
              . /vault/secrets/kafka.env
              python scripts/kafka/register_consumer_groups.py
          env:
            - name: KAFKA_BOOTSTRAP_SERVERS
              value: kafka.contextiq-data.svc.cluster.local:9092
          volumeMounts:
            - name: kafka-tls
              mountPath: /tls
              readOnly: true
          resources:
            requests: { cpu: "100m", memory: "128Mi" }
            limits:   { cpu: "300m", memory: "256Mi" }
      volumes:
        - name: kafka-tls
          secret:
            secretName: kafka-tls
```

## Acceptance Criteria

- [x] `kafka-consumer-groups.sh --bootstrap-server ... --list` shows all 6 group IDs (`indexing-service`, `graph-agent`, `context-retrieval`, `replay-service`, `audit-logger`, `health-monitor`) (AC-3)
- [x] `register_consumer_groups.py` exits 0; all groups show `STATE: Empty` (no active members — groups are pre-registered but not yet consuming) (AC-3)
- [x] Starting `indexing-service` with a missing topic raises a `RuntimeError` at startup containing the topic name and remediation message (AC-3)
- [x] Starting `indexing-service` with a valid topic and pre-registered group proceeds without error; `KafkaConsumerValidator.validate()` passes (AC-3)
- [x] `consumer-group-job` ArgoCD hook runs after `kafka-topic-bootstrap` (sync wave -4 vs -5) (AC-3)

## Dependencies

- TASK-US052-01 — Kafka brokers running with SCRAM-SHA-512 auth
- TASK-US052-02 — All 6 topics must exist before consumer group registration succeeds
- `src/kafka/topic_registry.py` (TASK-US052-02) — imported by `register_consumer_groups.py`

## Definition of Done

- [x] `register_consumer_groups.py` committed and idempotent in staging
- [x] `src/kafka/consumer_validator.py` and `src/kafka/consumer_base.py` committed with unit tests in `tests/unit/test_consumer_validator.py`
- [x] One service (e.g. `indexing-service`) updated to call `KafkaConsumerValidator.validate()` in its FastAPI lifespan and validated in staging
