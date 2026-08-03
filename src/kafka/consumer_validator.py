"""
AC-3: Startup validation — asserts that consumer group and topics exist on the broker
before the service starts processing. Used in FastAPI lifespan hooks.
"""
from __future__ import annotations

import logging
from typing import Any

from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import UnknownTopicOrPartitionError

from src.kafka.topic_registry import TOPIC_MAP, TopicSpec

logger = logging.getLogger(__name__)


class KafkaConsumerValidator:
    """
    Validates Kafka topics and consumer group membership at service startup.
    Raises RuntimeError if validation fails — surfaces as a pod startup failure (AC-3).
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
        # ---------------------------------------------------------------
        # 1. Topic validation via cluster metadata
        # NOTE: AIOKafkaAdminClient does not expose describe_topics() in
        # aiokafka >= 0.11. Use a temporary AIOKafkaConsumer instead:
        # after start(), the client fetches full cluster metadata and
        # partitions_for_topic() becomes available.
        # ---------------------------------------------------------------
        temp_consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap_servers,
            client_id=f"startup-validator-{self._group_id}",
            **self._sasl_kwargs,
        )
        await temp_consumer.start()
        try:
            for topic_name in self._topic_names:
                # partitions_for_topic() reads from cluster metadata cache populated by start()
                partitions = temp_consumer.partitions_for_topic(topic_name)
                if not partitions:
                    raise RuntimeError(
                        f"Kafka topic '{topic_name}' not found or has no partitions. "
                        f"Run kafka topic bootstrap before starting this service."
                    )
                spec: TopicSpec | None = TOPIC_MAP.get(topic_name)
                if spec and len(partitions) != spec.partitions:
                    raise RuntimeError(
                        f"Kafka topic '{topic_name}' has {len(partitions)} partitions, "
                        f"expected {spec.partitions}. Topic may need manual repair."
                    )
                logger.info(
                    "kafka_topic_validated",
                    extra={"topic": topic_name, "partitions": len(partitions)},
                )
        finally:
            await temp_consumer.stop()

        # ---------------------------------------------------------------
        # 2. Consumer group validation via admin client
        # ---------------------------------------------------------------
        admin = AIOKafkaAdminClient(
            bootstrap_servers=self._bootstrap_servers,
            client_id=f"startup-validator-admin-{self._group_id}",
            **self._sasl_kwargs,
        )
        await admin.start()
        try:
            group_descriptions = await admin.describe_consumer_groups([self._group_id])
            group = next(
                (g for g in group_descriptions if g.group_id == self._group_id),
                None,
            )
            if group is None:
                raise RuntimeError(
                    f"Consumer group '{self._group_id}' not found on broker. "
                    f"Run consumer group pre-registration job before deploying this service."
                )
            logger.info(
                "kafka_consumer_group_validated",
                extra={"group_id": self._group_id},
            )
        finally:
            await admin.close()
