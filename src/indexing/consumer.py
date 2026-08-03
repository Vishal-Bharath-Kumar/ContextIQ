"""IndexingConsumer — aiokafka consumer for the EP-008 indexing pipeline.

TASK-US027-04: Subscribes to ``knowledge.source.synced`` and
``knowledge.document.deleted`` topics, routes each message to either
``IndexingPipeline.run_for_source`` or ``DeletionHandler.handle``, and
commits offsets after successful processing (at-least-once semantics).
"""
from __future__ import annotations

import json
import logging
import os

from aiokafka import AIOKafkaConsumer
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.indexing.pipeline import IndexingPipeline
from src.indexing.schemas.events import DocumentDeletedEvent, SourceSyncedEvent
from src.indexing.stores.deletion_handler import DeletionHandler
from src.kafka.consumer_base import _sasl_kwargs

logger = logging.getLogger(__name__)


class IndexingConsumerSettings(BaseSettings):
    """Runtime-configurable Kafka consumer parameters.

    All fields are overridable via ``INDEXING_CONSUMER_*`` environment
    variables or a ``.env`` file at the project root.
    """

    model_config = SettingsConfigDict(
        env_prefix="INDEXING_CONSUMER_",
        env_file=".env",
    )

    # Falls back to the standard KAFKA_BOOTSTRAP_SERVERS env var (used by
    # every other Kafka client in this codebase) when the
    # INDEXING_CONSUMER_-prefixed override isn't set.
    kafka_bootstrap_servers: str = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    group_id: str = "contextiq-indexing-v2"  # v2: fresh group to bypass phantom consumer issue
    sync_topic: str = "knowledge.source.synced"
    deletion_topic: str = "knowledge.document.deleted"
    # Max Kafka messages fetched per poll iteration.
    max_poll_records: int = 100
    # Milliseconds to wait for new messages before iterating again.
    poll_timeout_ms: int = 1000
    # At-least-once: commit only after successful processing.
    enable_auto_commit: bool = False
    # Session timeout (ms) - time before Kafka considers consumer dead
    session_timeout_ms: int = 60000  # 60 seconds
    # Max poll interval (ms) - max time between poll() calls before rebalance
    max_poll_interval_ms: int = 300000  # 5 minutes


class IndexingConsumer:
    """Kafka consumer that drives the indexing pipeline for each synced source.

    Usage
    -----
    ::

        consumer = IndexingConsumer(pipeline, deletion_handler)
        await consumer.start()
        asyncio.create_task(consumer.run())
        # … on shutdown …
        await consumer.stop()

    At-least-once semantics
    -----------------------
    ``enable_auto_commit=False`` combined with an explicit ``await consumer.commit()``
    after each successful ``_handle_message`` call ensures the offset is only
    advanced once processing succeeds.  ``ChunkRepository.upsert_batch`` and
    ``QdrantIndexer.upsert`` are idempotent, so message redelivery on restart
    is safe.

    Poison-pill protection
    ----------------------
    Unhandled exceptions inside ``_handle_message`` are caught, logged, and the
    message offset is committed so a malformed message does not stall the loop.
    """

    def __init__(
        self,
        pipeline: IndexingPipeline,
        deletion_handler: DeletionHandler,
        settings: IndexingConsumerSettings | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._deletion_handler = deletion_handler
        self._settings = settings or IndexingConsumerSettings()
        self._consumer: AIOKafkaConsumer | None = None
        self._running: bool = False

    async def start(self) -> None:
        """Create and start the underlying AIOKafkaConsumer."""
        self._consumer = AIOKafkaConsumer(
            self._settings.sync_topic,
            self._settings.deletion_topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=self._settings.group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit=self._settings.enable_auto_commit,
            max_poll_records=self._settings.max_poll_records,
            session_timeout_ms=self._settings.session_timeout_ms,
            max_poll_interval_ms=self._settings.max_poll_interval_ms,
            **_sasl_kwargs(),
        )
        await self._consumer.start()
        self._running = True
        logger.warning(
            "indexing_consumer_started",
            extra={
                "sync_topic": self._settings.sync_topic,
                "deletion_topic": self._settings.deletion_topic,
                "group_id": self._settings.group_id,
                "bootstrap_servers": self._settings.kafka_bootstrap_servers,
                "enable_auto_commit": self._settings.enable_auto_commit,
                "session_timeout_ms": self._settings.session_timeout_ms,
                "max_poll_interval_ms": self._settings.max_poll_interval_ms,
            },
        )

    async def stop(self) -> None:
        """Signal the consume loop to exit and close the Kafka connection."""
        self._running = False
        if self._consumer is not None:
            await self._consumer.stop()

    async def run(self) -> None:
        """Blocking consume loop — run as an asyncio task from the lifespan.

        Raises
        ------
        RuntimeError
            If called before ``start()``.
        """
        if self._consumer is None:
            raise RuntimeError("Call start() before run()")

        print(f"🔄 CONSUMER_LOOP: entering async-for poll loop, partitions={sorted([tp.partition for tp in self._consumer.assignment()])}")
        async for msg in self._consumer:
            print(f"📨 CONSUMER_LOOP: received message from partition={msg.partition} offset={msg.offset}")
            if not self._running:
                break
            payload = msg.value if isinstance(msg.value, dict) else {}
            event_type = payload.get("event_type", "") if isinstance(payload, dict) else ""
            source_id = payload.get("source_id") if isinstance(payload, dict) else None
            job_id = payload.get("job_id") if isinstance(payload, dict) else None

            logger.warning(
                "indexing_consumer_message_received",
                extra={
                    "topic": msg.topic,
                    "partition": msg.partition,
                    "offset": msg.offset,
                    "event_type": event_type,
                    "source_id": str(source_id) if source_id is not None else None,
                    "job_id": str(job_id) if job_id is not None else None,
                },
            )

            result = await self._handle_message(msg)
            logger.warning(
                "indexing_consumer_message_handled",
                extra={
                    "topic": msg.topic,
                    "partition": msg.partition,
                    "offset": msg.offset,
                    "event_type": result["event_type"],
                    "source_id": result["source_id"],
                    "job_id": result["job_id"],
                    "status": result["status"],
                },
            )

            await self._consumer.commit()
            logger.warning(
                "indexing_consumer_offset_committed",
                extra={
                    "topic": msg.topic,
                    "partition": msg.partition,
                    "offset": msg.offset,
                    "event_type": result["event_type"],
                    "source_id": result["source_id"],
                    "job_id": result["job_id"],
                },
            )

    async def _handle_message(self, msg: object) -> dict[str, str | None]:  # type: ignore[type-arg]
        payload = msg.value  # type: ignore[union-attr]
        event_type = payload.get("event_type", "") if isinstance(payload, dict) else ""
        source_id = payload.get("source_id") if isinstance(payload, dict) else None
        job_id = payload.get("job_id") if isinstance(payload, dict) else None

        try:
            if event_type == "knowledge_source_synced":
                event = SourceSyncedEvent.model_validate(payload)
                count = await self._pipeline.run_for_source(
                    source_id=event.source_id,
                    tenant_id=event.tenant_id,
                )
                logger.info(
                    "Indexed %d chunks for source=%s job=%s",
                    count,
                    event.source_id,
                    event.job_id,
                )
            elif event_type == "knowledge_document_deleted":
                event = DocumentDeletedEvent.model_validate(payload)
                await self._deletion_handler.handle(
                    document_id=event.document_id,
                    source_id=event.source_id,
                    tenant_id=event.tenant_id,
                )
                logger.info(
                    "Deleted stale embeddings for document=%s source=%s",
                    event.document_id,
                    event.source_id,
                )
            else:
                logger.warning(
                    "IndexingConsumer: unknown event_type=%s — skipping",
                    event_type,
                )
            return {
                "event_type": event_type,
                "source_id": str(source_id) if source_id is not None else None,
                "job_id": str(job_id) if job_id is not None else None,
                "status": "ok",
            }
        except Exception:
            # Log and skip the message rather than crashing the consumer loop.
            # The commit below will advance the offset; this is intentional:
            # poison-pill messages must not halt the pipeline for all sources.
            logger.exception("IndexingConsumer: failed to process message; skipping")
            return {
                "event_type": event_type,
                "source_id": str(source_id) if source_id is not None else None,
                "job_id": str(job_id) if job_id is not None else None,
                "status": "failed",
            }
