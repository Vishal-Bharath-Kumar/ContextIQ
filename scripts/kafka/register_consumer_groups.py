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

# Ensure the repo root is on sys.path so src.kafka is importable inside the container
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from aiokafka import AIOKafkaConsumer  # noqa: E402
from aiokafka.errors import UnknownTopicOrPartitionError  # noqa: E402

from src.kafka.topic_registry import TOPICS  # noqa: E402


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
        # assignment() returns partitions assigned during group join (happens in start())
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

    # Build group → topics mapping from the canonical topic registry
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
