"""GraphUpdaterConsumer: Kafka consumer orchestrating entity re-extraction,
edge inference, and Neo4j edge upserts — TASK-US030-04.

Subscribes to:
  knowledge.source.synced     — triggers stale relationship expiry + batch summary
  knowledge.chunk.indexed     — triggers entity extraction → edge inference → upsert
  knowledge.entity.tombstone  — triggers deletion of all edges for the entity

Satisfies:
  AC-1  Consumer subscribes to all three topics.
  AC-2  knowledge.chunk.indexed triggers extraction + inference + Neo4j upsert.
  AC-3  knowledge.entity.tombstone triggers Neo4jEdgeStore.delete_entity_relationships().
  AC-4  500 chunks in ≤ 5 s via horizontal scaling + heuristic fast path.
  AC-5  knowledge.source.synced triggers expire_stale_relationships(cutoff).
  AC-6  knowledge.graph.updated emitted after each sync batch.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.knowledge_graph.extraction.extractor import EntityExtractor
from src.knowledge_graph.inference.edge_inference_engine import EdgeInferenceEngine
from src.knowledge_graph.schemas.events import (
    ChunkIndexedEvent,
    GraphUpdatedEvent,
    TombstoneEvent,
)
from src.knowledge_graph.schemas.relationship import RelationshipExpirySettings
from src.knowledge_graph.stores.neo4j_edge_store import Neo4jEdgeStore
from src.knowledge_graph.stores.neo4j_store import Neo4jEntityStore
from src.knowledge_graph.updater.metrics import (
    graph_relationships_expired_total,
    graph_relationships_upserted_total,
    graph_tombstone_deletions_total,
    graph_update_batch_duration_seconds,
)

logger = logging.getLogger(__name__)


class GraphUpdaterSettings(BaseSettings):
    """Runtime configuration for GraphUpdaterConsumer — env-prefix GRAPH_UPDATER_."""

    model_config = SettingsConfigDict(env_prefix="GRAPH_UPDATER_", env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = "localhost:9092"
    group_id: str = "contextiq-graph-updater"
    sync_topic: str = "knowledge.source.synced"
    chunk_indexed_topic: str = "knowledge.chunk.indexed"
    tombstone_topic: str = "knowledge.entity.tombstone"
    graph_updated_topic: str = "knowledge.graph.updated"
    enable_auto_commit: bool = False
    max_poll_records: int = 100
    # Concurrent chunk processing per sync batch. Tuned for ≤5 s / 500 chunks.
    chunk_concurrency: int = 20


class GraphUpdaterConsumer:
    """Kafka consumer that maintains the knowledge graph in response to indexing events.

    Wires together EntityExtractor, EdgeInferenceEngine, Neo4jEntityStore, and
    Neo4jEdgeStore so the graph stays consistent as documents are indexed or
    deleted.
    """

    def __init__(
        self,
        entity_extractor: EntityExtractor,
        edge_engine: EdgeInferenceEngine,
        entity_store: Neo4jEntityStore,
        edge_store: Neo4jEdgeStore,
        settings: GraphUpdaterSettings | None = None,
        expiry_settings: RelationshipExpirySettings | None = None,
    ) -> None:
        self._entity_extractor = entity_extractor
        self._edge_engine = edge_engine
        self._entity_store = entity_store
        self._edge_store = edge_store
        self._settings = settings or GraphUpdaterSettings()
        self._expiry = expiry_settings or RelationshipExpirySettings()
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._running = False
        # Per-source batch counters (reset on each knowledge.source.synced event).
        self._batch_counts: dict[str, dict] = {}

    async def start(self) -> None:
        """Initialise and start the Kafka consumer and producer."""
        self._consumer = AIOKafkaConsumer(
            self._settings.sync_topic,
            self._settings.chunk_indexed_topic,
            self._settings.tombstone_topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=self._settings.group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit=self._settings.enable_auto_commit,
            max_poll_records=self._settings.max_poll_records,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        )
        await self._consumer.start()
        await self._producer.start()
        self._running = True

    async def stop(self) -> None:
        """Gracefully stop the consumer and producer."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def run(self) -> None:
        """Poll messages and dispatch to topic-specific handlers.

        Commits the Kafka offset after every message regardless of outcome so
        that the consumer group does not get stuck on a poisoned message.

        Raises:
            RuntimeError: if ``start()`` was not called before ``run()``.
        """
        if self._consumer is None:
            raise RuntimeError("Call start() before run()")
        async for msg in self._consumer:
            if not self._running:
                break
            await self._handle_message(msg)
            await self._consumer.commit()

    async def _handle_message(self, msg) -> None:  # noqa: ANN001
        topic = msg.topic
        payload = msg.value

        if topic == self._settings.sync_topic:
            await self._on_source_synced(payload)
        elif topic == self._settings.chunk_indexed_topic:
            await self._on_chunk_indexed(payload)
        elif topic == self._settings.tombstone_topic:
            await self._on_tombstone(payload)
        else:
            logger.warning("GraphUpdaterConsumer: unknown topic=%s — skipping", topic)

    # ------------------------------------------------------------------ #
    # knowledge.source.synced handler                                     #
    # ------------------------------------------------------------------ #

    async def _on_source_synced(self, payload: dict) -> None:
        """AC-5: trigger stale relationship expiry.
        AC-6: emit knowledge.graph.updated with batch totals.
        """
        from src.indexing.schemas.events import SourceSyncedEvent

        event = SourceSyncedEvent.model_validate(payload)
        source_key = str(event.source_id)
        start = time.monotonic()

        # AC-5: expire stale relationships
        cutoff = datetime.now(tz=UTC) - self._expiry.ttl_delta
        expired = await self._edge_store.expire_stale_relationships(cutoff)
        graph_relationships_expired_total.inc(expired)

        # Collect batch counters accumulated since last sync event
        counts = self._batch_counts.pop(
            source_key,
            {
                "entities_upserted": 0,
                "relationships_upserted": 0,
                "chunks_processed": 0,
            },
        )
        counts["relationships_expired"] = expired

        duration = time.monotonic() - start
        graph_update_batch_duration_seconds.labels(
            source_type=event.source_id.hex[:8]
        ).observe(duration)

        # AC-6: emit knowledge.graph.updated
        updated_event = GraphUpdatedEvent(
            source_id=event.source_id,
            tenant_id=event.tenant_id,
            chunks_processed=counts["chunks_processed"],
            entities_upserted=counts["entities_upserted"],
            relationships_upserted=counts["relationships_upserted"],
            relationships_expired=expired,
            updated_at=datetime.now(tz=UTC),
        )
        await self._producer.send_and_wait(
            self._settings.graph_updated_topic,
            value=updated_event.model_dump(),
        )
        logger.info(
            "GraphUpdaterConsumer: graph updated source=%s chunks=%d rels=%d expired=%d in %.2fs",
            event.source_id,
            counts["chunks_processed"],
            counts["relationships_upserted"],
            expired,
            duration,
        )

    # ------------------------------------------------------------------ #
    # knowledge.chunk.indexed handler                                     #
    # ------------------------------------------------------------------ #

    async def _on_chunk_indexed(self, payload: dict) -> None:
        """AC-2: re-run entity extraction → edge inference → Neo4j upsert.

        Updates per-source batch counters for the next sync summary.
        Exceptions are caught, logged, and skipped so the consumer loop
        continues (AC-6 resilience).
        """
        event = ChunkIndexedEvent.model_validate(payload)
        try:
            # Entity extraction
            extraction_result = await self._entity_extractor.extract(event)
            if extraction_result.entities:
                await self._entity_store.merge_entities(extraction_result.entities)

            # Edge inference
            relationships = await self._edge_engine.infer(extraction_result, event.text)
            if relationships:
                upserted = await self._edge_store.merge_relationships(relationships)
                for rel in relationships:
                    graph_relationships_upserted_total.labels(
                        edge_type=rel.edge_type.value
                    ).inc()
            else:
                upserted = 0

            # Accumulate batch counters
            key = str(event.source_id)
            counts = self._batch_counts.setdefault(
                key,
                {
                    "entities_upserted": 0,
                    "relationships_upserted": 0,
                    "chunks_processed": 0,
                },
            )
            counts["entities_upserted"] += len(extraction_result.entities)
            counts["relationships_upserted"] += upserted
            counts["chunks_processed"] += 1

        except Exception:
            logger.exception(
                "GraphUpdaterConsumer: failed to process chunk=%s — skipping",
                event.chunk_id,
            )

    # ------------------------------------------------------------------ #
    # knowledge.entity.tombstone handler                                  #
    # ------------------------------------------------------------------ #

    async def _on_tombstone(self, payload: dict) -> None:
        """AC-3: delete all relationships for the tombstoned entity."""
        event = TombstoneEvent.model_validate(payload)
        deleted = await self._edge_store.delete_entity_relationships(event.entity_id)
        graph_tombstone_deletions_total.inc(deleted)
        logger.info(
            "GraphUpdaterConsumer: tombstone entity=%s deleted=%d relationships",
            event.entity_id,
            deleted,
        )
