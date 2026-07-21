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


def _retention_config(spec: TopicSpec, replication_cap: int = 3) -> dict[str, str]:
    # min.insync.replicas must never exceed the replication factor actually
    # in use, or acks=all produces would fail with NOT_ENOUGH_REPLICAS.
    # Production runs 3 brokers (min.insync.replicas=2); a single-broker
    # local/dev cluster falls back to 1.
    min_isr = min(2, replication_cap)
    return {
        "retention.ms":        str(spec.retention_ms),
        "cleanup.policy":      spec.cleanup_policy,
        "min.insync.replicas": str(min_isr),   # durability: N-1 of replication_cap brokers must ack
        "compression.type":    "lz4",   # compress all topics for bandwidth efficiency
    }


def main() -> int:
    _log("topic_bootstrap_start", topics=[t.name for t in TOPICS])

    admin = _make_admin()

    # Cap replication factor to the number of brokers actually registered in
    # the cluster. In production (3+ brokers) this is a no-op — min() returns
    # the configured replication_factor unchanged. It allows the same topic
    # registry to bootstrap correctly against a single-broker local/dev
    # Kafka cluster, where a replication_factor of 3 would otherwise be
    # unsatisfiable.
    replication_cap = max(1, len(admin.describe_cluster()["brokers"]))
    _log("broker_count", count=replication_cap)

    # Fetch existing topics
    existing_topics: set[str] = set(admin.list_topics())
    _log("existing_topics", count=len(existing_topics), topics=sorted(existing_topics))

    to_create: list[NewTopic] = []

    for spec in TOPICS:
        if spec.name in existing_topics:
            _log("topic_already_exists", topic=spec.name)
            # Validate partition count (cannot be reduced, only increased)
            # kafka-python describe_topics() returns a list of dicts — the
            # partition list is under the "partitions" key, not a namedtuple
            # attribute.
            meta = admin.describe_topics([spec.name])
            actual_partitions: int = len(meta[0]["partitions"]) if meta else spec.partitions
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
                    replication_factor=min(spec.replication_factor, replication_cap),
                    topic_configs=_retention_config(spec, replication_cap),
                )
            )

    if to_create:
        _log("creating_topics", count=len(to_create), names=[t.name for t in to_create])
        try:
            admin.create_topics(new_topics=to_create, validate_only=False)
        except TopicAlreadyExistsError:
            _log("some_topics_already_exist_race_condition", level="WARNING")

    # Apply/update retention configs for all pre-existing topics (idempotent).
    # alter_configs() takes a list of ConfigResource objects that already
    # carry their `configs` dict — not a {ConfigResource: dict} mapping.
    config_resources: list[ConfigResource] = [
        ConfigResource(
            ConfigResourceType.TOPIC, spec.name,
            configs=_retention_config(spec, replication_cap),
        )
        for spec in TOPICS
        if spec.name in existing_topics
    ]
    if config_resources:
        admin.alter_configs(config_resources)
        _log("retention_configs_applied", topic_count=len(config_resources))

    # Final verification — all 6 topics must be present.
    # create_topics() can return before the new topics are visible in
    # cluster metadata, so retry briefly instead of failing immediately.
    missing: list[str] = []
    for attempt in range(1, MAX_RETRIES + 1):
        final_topics: set[str] = set(admin.list_topics())
        missing = [spec.name for spec in TOPICS if spec.name not in final_topics]
        if not missing:
            break
        _log("topic_verification_pending", attempt=attempt, missing_topics=missing)
        time.sleep(RETRY_DELAY_S)

    if missing:
        _log("topic_bootstrap_failed", missing_topics=missing)
        admin.close()
        return 1

    _log("topic_bootstrap_complete", total_topics=len(TOPICS))
    admin.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
