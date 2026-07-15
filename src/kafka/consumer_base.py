"""
Base AIOKafka consumer wrapper.
Each service subclasses this and implements process_message().
"""
from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
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


class BaseKafkaConsumer(ABC):
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
        # Store the task reference to prevent it being garbage-collected while pending
        self._consume_task: asyncio.Task[None] | None = None

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
        # Store the task reference so the garbage collector doesn't destroy a pending task
        self._consume_task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        if self._consume_task and not self._consume_task.done():
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()

    async def _consume_loop(self) -> None:
        if self._consumer is None:
            return
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
