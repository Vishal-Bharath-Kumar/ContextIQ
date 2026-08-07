"""EntityConsumer: Kafka consumer with retry and dead-letter queue — TASK-US028-04.

Subscribes to ``knowledge.chunk.indexed`` and ``knowledge.chunk.indexed.retry``,
calls ``EntityExtractor.extract()``, and writes results via
``Neo4jEntityStore.merge_entities()``.

On failure the chunk is re-queued up to ``max_retries`` times before being
sent to the dead-letter topic and logged (AC-6).  Offsets are committed only
after the message is fully handled — success, re-queue, or DLQ (AC-1).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.kafka.consumer_base import BOOTSTRAP_SERVERS, _sasl_kwargs

from src.knowledge_graph.extraction.extractor import EntityExtractor
from src.knowledge_graph.metrics import (
    entities_extracted_total,
    entity_extraction_duration_ms,
    entity_extraction_total,
)
from src.knowledge_graph.schemas.events import (
    ChunkIndexedEvent,
    ChunkRetryEnvelope,
    EntityExtractionFailedEvent,
)
from src.knowledge_graph.stores.neo4j_store import Neo4jEntityStore

logger = logging.getLogger(__name__)


class EntityConsumerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENTITY_CONSUMER_", env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = BOOTSTRAP_SERVERS
    group_id: str = "contextiq-entity-extraction"
    chunk_indexed_topic: str = "knowledge.chunk.indexed"
    retry_topic: str = "knowledge.chunk.indexed.retry"
    dead_letter_topic: str = "knowledge.entity.extraction.dlq"
    # Number of re-queue attempts before sending to DLQ.
    max_retries: int = 3
    enable_auto_commit: bool = False
    max_poll_records: int = 50


class EntityConsumer:
    """Consumes chunk-indexed events and drives entity extraction into Neo4j.

    Start via ``await consumer.start()``, then block on ``await consumer.run()``.
    Stop gracefully via ``await consumer.stop()``.
    """

    def __init__(
        self,
        extractor: EntityExtractor,
        neo4j_store: Neo4jEntityStore,
        settings: EntityConsumerSettings | None = None,
    ) -> None:
        self._extractor = extractor
        self._neo4j_store = neo4j_store
        self._settings = settings or EntityConsumerSettings()
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._running = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._settings.chunk_indexed_topic,
            self._settings.retry_topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=self._settings.group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit=self._settings.enable_auto_commit,
            max_poll_records=self._settings.max_poll_records,
            **_sasl_kwargs(),
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            **_sasl_kwargs(),
        )
        await self._consumer.start()
        await self._producer.start()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def run(self) -> None:
        """Blocking consume loop. Run as asyncio.create_task from lifespan."""
        if self._consumer is None:
            raise RuntimeError("Call start() before run()")
        async for msg in self._consumer:
            if not self._running:
                break
            await self._handle_message(msg)
            await self._consumer.commit()

    async def _handle_message(self, msg: object) -> None:
        """Dispatch to the correct handler based on topic."""
        payload = msg.value  # type: ignore[attr-defined]
        if msg.topic == self._settings.retry_topic:  # type: ignore[attr-defined]
            envelope = ChunkRetryEnvelope.model_validate(payload)
            await self._process_chunk(envelope.original, attempt=envelope.attempt)
        else:
            event = ChunkIndexedEvent.model_validate(payload)
            await self._process_chunk(event, attempt=1)

    async def _process_chunk(self, event: ChunkIndexedEvent, attempt: int) -> None:
        try:
            result = await self._extractor.extract(event)

            entity_extraction_duration_ms.labels(
                model_id=self._extractor._settings.model_id
            ).observe(result.duration_ms)
            entity_extraction_total.labels(status="success").inc()

            await self._neo4j_store.merge_entities(result.entities)

            for entity in result.entities:
                entities_extracted_total.labels(entity_type=entity.entity_type.value).inc()

        except Exception as exc:
            logger.warning(
                "EntityConsumer: extraction failed chunk=%s attempt=%d error=%s",
                event.chunk_id,
                attempt,
                exc,
            )
            if attempt < self._settings.max_retries:
                entity_extraction_total.labels(status="retried").inc()
                await self._requeue(event, attempt + 1)
            else:
                entity_extraction_total.labels(status="dead_lettered").inc()
                await self._send_to_dlq(event, attempt, str(exc))

    async def _requeue(self, event: ChunkIndexedEvent, next_attempt: int) -> None:
        envelope = ChunkRetryEnvelope(attempt=next_attempt, original=event)
        await self._producer.send_and_wait(  # type: ignore[union-attr]
            self._settings.retry_topic,
            value=envelope.model_dump(),
        )
        logger.info(
            "EntityConsumer: re-queued chunk=%s as attempt %d",
            event.chunk_id,
            next_attempt,
        )

    async def _send_to_dlq(
        self, event: ChunkIndexedEvent, attempt: int, error: str
    ) -> None:
        failed_event = EntityExtractionFailedEvent(
            chunk_id=event.chunk_id,
            source_id=event.source_id,
            tenant_id=event.tenant_id,
            error=error,
            failed_at=datetime.now(tz=UTC),
            attempt=attempt,
        )
        await self._producer.send_and_wait(  # type: ignore[union-attr]
            self._settings.dead_letter_topic,
            value=failed_event.model_dump(),
        )
        logger.error(
            "EntityConsumer: chunk=%s exhausted %d retries; sent to DLQ. error=%s",
            event.chunk_id,
            attempt,
            error,
        )
