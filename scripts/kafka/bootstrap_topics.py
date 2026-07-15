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

from kafka.admin import (
    ConfigResource,
    ConfigResourceType,
    KafkaAdminClient,
    NewPartitions,
    NewTopic,
)
from kafka.errors import NoBrokersAvailable, TopicAlreadyExistsError

# Ensure the repo root is on sys.path so src.kafka is importable inside the container
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.kafka.topic_registry import TOPICS, TopicSpec  # noqa: E402


BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.contextiq-data.svc.cluster.local:9092",
)
KAFKA_USERNAME = os.environ.get("KAFKA_USERNAME", "")
KAFKA_PASSWORD = os.environ.get("KAFKA_PASSWORD", "")

MAX_RETRIES   = 10
RETRY_DELAY_S = 6


def _log(event: str, **kwargs: Any) -> None:
    print(json.dumps({"event": event, **kwargs}), flush=True)


def _make_admin() -> KafkaAdminClient:
    """Create a KafkaAdminClient with SCRAM-SHA-512 auth; retry on NoBrokersAvailable."""
    kwargs: dict[str, Any] = {
        "bootstrap_servers":   BOOTSTRAP_SERVERS,
        "client_id":           "topic-bootstrap",
        "security_protocol":   "SASL_SSL",
        "sasl_mechanism":      "SCRAM-SHA-512",
        "sasl_plain_username": KAFKA_USERNAME,
        "sasl_plain_password": KAFKA_PASSWORD,
        "ssl_cafile":          "/tls/ca.crt",
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
        "min.insync.replicas": "2",     # durability: 2-of-3 brokers must ack
        "compression.type":    "lz4",   # compress all topics for bandwidth efficiency
    }


def main() -> int:
    _log("topic_bootstrap_start", topics=[t.name for t in TOPICS])

    admin = _make_admin()

    # Fetch existing topics
    existing_topics: set[str] = set(admin.list_topics())
    _log("existing_topics", count=len(existing_topics), topics=sorted(existing_topics))

    to_create: list[NewTopic] = []

    for spec in TOPICS:
        if spec.name in existing_topics:
            _log("topic_already_exists", topic=spec.name)
            # Validate partition count (cannot be reduced, only increased)
            # kafka-python describe_topics() returns namedtuples — use .partitions attribute
            meta = admin.describe_topics([spec.name])
            actual_partitions: int = len(meta[0].partitions) if meta else spec.partitions
            if actual_partitions != spec.partitions:
                _log(
                    "topic_partition_drift",
                    topic=spec.name,
                    expected=spec.partitions,
                    actual=actual_partitions,
                    level="WARNING",
                )
                if actual_partitions < spec.partitions:
                    _log(
                        "topic_increasing_partitions",
                        topic=spec.name,
                        new_count=spec.partitions,
                    )
                    # create_partitions() requires a NewPartitions object, not a plain integer
                    admin.create_partitions(
                        {spec.name: NewPartitions(total_count=spec.partitions)}
                    )
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

    # Apply/update retention configs for all pre-existing topics (idempotent).
    # alter_configs() requires {ConfigResource: {key: value}}, not {str: {key: value}}.
    config_resources: dict[ConfigResource, dict[str, str]] = {
        ConfigResource(ConfigResourceType.TOPIC, spec.name): _retention_config(spec)
        for spec in TOPICS
        if spec.name in existing_topics
    }
    if config_resources:
        admin.alter_configs(config_resources)
        _log("retention_configs_applied", topic_count=len(config_resources))

    # Final verification — all 6 topics must be present
    final_topics: set[str] = set(admin.list_topics())
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
