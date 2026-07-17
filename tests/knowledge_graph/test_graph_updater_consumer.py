"""Tests for GraphUpdaterConsumer — TASK-US030-04.

Covers all acceptance criteria using AsyncMock; no live Kafka or Neo4j in CI.
  AC-1  Consumer subscribes to all three topics.
  AC-2  knowledge.chunk.indexed triggers extraction + inference + Neo4j upsert.
  AC-3  knowledge.entity.tombstone triggers delete_entity_relationships().
  AC-4  Exception in _on_chunk_indexed is logged and skipped; consumer loop continues.
  AC-5  knowledge.source.synced triggers expire_stale_relationships(cutoff).
  AC-6  knowledge.graph.updated emitted with correct batch counters.
  AC-7  Kafka offset committed after every message regardless of outcome.
  AC-8  run() raises RuntimeError when start() was not called.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.schemas.entity import (
    EntityExtractionResult,
    EntityType,
    ExtractedEntity,
    make_entity_id,
)
from src.knowledge_graph.schemas.events import ChunkIndexedEvent, GraphUpdatedEvent, TombstoneEvent
from src.knowledge_graph.schemas.relationship import GraphRelationship, RelationshipExpirySettings
from src.knowledge_graph.updater.consumer import GraphUpdaterConsumer, GraphUpdaterSettings

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_CHUNK_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_SOURCE_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")
_TENANT_ID = "tenant-1"
_NOW = datetime(2025, 6, 1, tzinfo=UTC)

_SETTINGS = GraphUpdaterSettings(
    kafka_bootstrap_servers="localhost:9092",
    group_id="test-graph-updater",
    sync_topic="knowledge.source.synced",
    chunk_indexed_topic="knowledge.chunk.indexed",
    tombstone_topic="knowledge.entity.tombstone",
    graph_updated_topic="knowledge.graph.updated",
    enable_auto_commit=False,
    max_poll_records=10,
    chunk_concurrency=5,
)

_EXPIRY_SETTINGS = RelationshipExpirySettings(ttl_days=30)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity() -> ExtractedEntity:
    canonical = "auth service"
    return ExtractedEntity(
        entity_id=make_entity_id(EntityType.SERVICE, canonical),
        entity_type=EntityType.SERVICE,
        name="Auth Service",
        canonical_name=canonical,
        source_id=_SOURCE_ID,
        chunk_id=_CHUNK_ID,
        created_at=_NOW,
    )


def _make_extraction_result(entities: list[ExtractedEntity] | None = None) -> EntityExtractionResult:
    if entities is None:
        entities = [_make_entity()]
    return EntityExtractionResult(
        chunk_id=_CHUNK_ID,
        source_id=_SOURCE_ID,
        entities=entities,
        duration_ms=80.0,
    )


def _make_relationship() -> GraphRelationship:
    return GraphRelationship.create(
        from_entity_id=make_entity_id(EntityType.SERVICE, "auth service"),
        to_entity_id=make_entity_id(EntityType.SERVICE, "user service"),
        edge_type=EdgeType.DEPENDS_ON,
        source_id=_SOURCE_ID,
        chunk_id=_CHUNK_ID,
        ttl_days=30,
    )


def _make_chunk_indexed_payload() -> dict:
    return {
        "event_type": "knowledge_chunk_indexed",
        "chunk_id": str(_CHUNK_ID),
        "source_id": str(_SOURCE_ID),
        "tenant_id": _TENANT_ID,
        "document_id": "doc-1",
        "text": "Deploy auth service to production",
        "token_count": 10,
        "embedding_model": "text-embedding-3-small",
        "indexed_at": _NOW.isoformat(),
    }


def _make_source_synced_payload(source_id: UUID | None = None) -> dict:
    return {
        "event_type": "knowledge_source_synced",
        "source_id": str(source_id or _SOURCE_ID),
        "tenant_id": _TENANT_ID,
        "job_id": str(uuid4()),
        "items_processed": 10,
        "synced_at": _NOW.isoformat(),
    }


def _make_tombstone_payload(entity_id: str = "a" * 16) -> dict:
    return {
        "event_type": "knowledge_entity_tombstone",
        "entity_id": entity_id,
        "source_id": str(_SOURCE_ID),
        "tenant_id": _TENANT_ID,
        "document_id": "doc-1",
        "deleted_at": _NOW.isoformat(),
    }


def _make_kafka_message(topic: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(topic=topic, value=value)


def _make_consumer() -> tuple[GraphUpdaterConsumer, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Return (consumer, mock_extractor, mock_edge_engine, mock_entity_store, mock_edge_store)."""
    mock_extractor = MagicMock()
    mock_extractor.extract = AsyncMock(return_value=_make_extraction_result())

    mock_edge_engine = MagicMock()
    mock_edge_engine.infer = AsyncMock(return_value=[_make_relationship()])

    mock_entity_store = AsyncMock()
    mock_entity_store.merge_entities = AsyncMock()

    mock_edge_store = AsyncMock()
    mock_edge_store.merge_relationships = AsyncMock(return_value=1)
    mock_edge_store.expire_stale_relationships = AsyncMock(return_value=3)
    mock_edge_store.delete_entity_relationships = AsyncMock(return_value=2)

    consumer = GraphUpdaterConsumer(
        entity_extractor=mock_extractor,
        edge_engine=mock_edge_engine,
        entity_store=mock_entity_store,
        edge_store=mock_edge_store,
        settings=_SETTINGS,
        expiry_settings=_EXPIRY_SETTINGS,
    )
    return consumer, mock_extractor, mock_edge_engine, mock_entity_store, mock_edge_store


# ---------------------------------------------------------------------------
# AC-8: run() guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_raises_if_start_not_called() -> None:
    consumer, *_ = _make_consumer()
    with pytest.raises(RuntimeError, match="Call start()"):
        await consumer.run()


# ---------------------------------------------------------------------------
# AC-1: start() creates consumer subscribing to all three topics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_subscribes_to_all_three_topics() -> None:
    consumer, *_ = _make_consumer()

    mock_kafka_consumer = AsyncMock()
    mock_kafka_producer = AsyncMock()

    with (
        patch(
            "src.knowledge_graph.updater.consumer.AIOKafkaConsumer",
            return_value=mock_kafka_consumer,
        ) as mock_consumer_cls,
        patch(
            "src.knowledge_graph.updater.consumer.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ),
    ):
        await consumer.start()

        call_args = mock_consumer_cls.call_args
        assert _SETTINGS.sync_topic in call_args.args
        assert _SETTINGS.chunk_indexed_topic in call_args.args
        assert _SETTINGS.tombstone_topic in call_args.args

        mock_kafka_consumer.start.assert_awaited_once()
        mock_kafka_producer.start.assert_awaited_once()
        assert consumer._running is True


# ---------------------------------------------------------------------------
# AC-2: knowledge.chunk.indexed triggers extraction + inference + Neo4j upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_chunk_indexed_calls_extractor_and_stores() -> None:
    consumer, mock_extractor, mock_edge_engine, mock_entity_store, mock_edge_store = _make_consumer()
    payload = _make_chunk_indexed_payload()

    with (
        patch("src.knowledge_graph.updater.consumer.graph_relationships_upserted_total") as mock_counter,
    ):
        mock_counter.labels.return_value = MagicMock()
        await consumer._on_chunk_indexed(payload)

    mock_extractor.extract.assert_awaited_once()
    event_arg = mock_extractor.extract.call_args.args[0]
    assert event_arg.chunk_id == _CHUNK_ID

    mock_entity_store.merge_entities.assert_awaited_once()
    mock_edge_engine.infer.assert_awaited_once()
    mock_edge_store.merge_relationships.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_chunk_indexed_increments_batch_counters() -> None:
    consumer, *_ = _make_consumer()
    payload = _make_chunk_indexed_payload()

    with patch("src.knowledge_graph.updater.consumer.graph_relationships_upserted_total") as mock_counter:
        mock_counter.labels.return_value = MagicMock()
        await consumer._on_chunk_indexed(payload)

    source_key = str(_SOURCE_ID)
    assert source_key in consumer._batch_counts
    counts = consumer._batch_counts[source_key]
    assert counts["chunks_processed"] == 1
    assert counts["entities_upserted"] == 1
    assert counts["relationships_upserted"] == 1


@pytest.mark.asyncio
async def test_on_chunk_indexed_skips_entity_store_when_no_entities() -> None:
    consumer, mock_extractor, mock_edge_engine, mock_entity_store, mock_edge_store = _make_consumer()
    mock_extractor.extract = AsyncMock(return_value=_make_extraction_result(entities=[]))
    mock_edge_engine.infer = AsyncMock(return_value=[])
    payload = _make_chunk_indexed_payload()

    await consumer._on_chunk_indexed(payload)

    mock_entity_store.merge_entities.assert_not_awaited()
    mock_edge_store.merge_relationships.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_chunk_indexed_increments_relationship_counter() -> None:
    consumer, *_ = _make_consumer()
    payload = _make_chunk_indexed_payload()

    with patch(
        "src.knowledge_graph.updater.consumer.graph_relationships_upserted_total"
    ) as mock_counter:
        label_mock = MagicMock()
        mock_counter.labels.return_value = label_mock
        await consumer._on_chunk_indexed(payload)

    mock_counter.labels.assert_called_once_with(edge_type=EdgeType.DEPENDS_ON.value)
    label_mock.inc.assert_called_once()


# ---------------------------------------------------------------------------
# AC-4: Exception in _on_chunk_indexed is caught and skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_chunk_indexed_exception_is_logged_and_skipped() -> None:
    consumer, mock_extractor, *_ = _make_consumer()
    mock_extractor.extract = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    payload = _make_chunk_indexed_payload()

    # Should not raise
    await consumer._on_chunk_indexed(payload)

    # Batch counters should not be updated
    assert str(_SOURCE_ID) not in consumer._batch_counts


# ---------------------------------------------------------------------------
# AC-3: knowledge.entity.tombstone triggers delete_entity_relationships
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_tombstone_calls_delete_entity_relationships() -> None:
    consumer, _, _, _, mock_edge_store = _make_consumer()
    entity_id = "b" * 16
    payload = _make_tombstone_payload(entity_id=entity_id)

    with patch(
        "src.knowledge_graph.updater.consumer.graph_tombstone_deletions_total"
    ) as mock_counter:
        await consumer._on_tombstone(payload)

    mock_edge_store.delete_entity_relationships.assert_awaited_once_with(entity_id)
    mock_counter.inc.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# AC-5 + AC-6: knowledge.source.synced triggers expiry and emits updated event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_source_synced_triggers_stale_expiry_and_emits_event() -> None:
    consumer, _, _, _, mock_edge_store = _make_consumer()
    consumer._producer = AsyncMock()

    # Pre-populate batch counters as if chunks were processed
    source_key = str(_SOURCE_ID)
    consumer._batch_counts[source_key] = {
        "entities_upserted": 5,
        "relationships_upserted": 3,
        "chunks_processed": 2,
    }

    payload = _make_source_synced_payload()

    with (
        patch(
            "src.knowledge_graph.updater.consumer.graph_relationships_expired_total"
        ) as mock_expired_counter,
        patch(
            "src.knowledge_graph.updater.consumer.graph_update_batch_duration_seconds"
        ) as mock_hist,
    ):
        mock_hist.labels.return_value = MagicMock()
        await consumer._on_source_synced(payload)

    # AC-5: stale expiry called
    mock_edge_store.expire_stale_relationships.assert_awaited_once()
    cutoff_arg = mock_edge_store.expire_stale_relationships.call_args.args[0]
    expected_cutoff = datetime.now(tz=UTC) - timedelta(days=30)
    assert abs((cutoff_arg - expected_cutoff).total_seconds()) < 5

    # Expired counter incremented
    mock_expired_counter.inc.assert_called_once_with(3)

    # AC-6: graph.updated emitted with correct counts
    consumer._producer.send_and_wait.assert_awaited_once()
    call_args = consumer._producer.send_and_wait.call_args
    assert call_args.args[0] == _SETTINGS.graph_updated_topic
    emitted = call_args.kwargs["value"]
    assert emitted["chunks_processed"] == 2
    assert emitted["entities_upserted"] == 5
    assert emitted["relationships_upserted"] == 3
    assert emitted["relationships_expired"] == 3


@pytest.mark.asyncio
async def test_on_source_synced_clears_batch_counters() -> None:
    consumer, _, _, _, _ = _make_consumer()
    consumer._producer = AsyncMock()

    source_key = str(_SOURCE_ID)
    consumer._batch_counts[source_key] = {
        "entities_upserted": 2,
        "relationships_upserted": 1,
        "chunks_processed": 1,
    }

    with (
        patch("src.knowledge_graph.updater.consumer.graph_relationships_expired_total"),
        patch("src.knowledge_graph.updater.consumer.graph_update_batch_duration_seconds") as mock_hist,
    ):
        mock_hist.labels.return_value = MagicMock()
        await consumer._on_source_synced(_make_source_synced_payload())

    # Batch counts cleared after sync
    assert source_key not in consumer._batch_counts


@pytest.mark.asyncio
async def test_on_source_synced_emits_zeros_when_no_chunks_processed() -> None:
    consumer, _, _, _, _ = _make_consumer()
    consumer._producer = AsyncMock()

    # No batch counters pre-populated
    with (
        patch("src.knowledge_graph.updater.consumer.graph_relationships_expired_total"),
        patch("src.knowledge_graph.updater.consumer.graph_update_batch_duration_seconds") as mock_hist,
    ):
        mock_hist.labels.return_value = MagicMock()
        await consumer._on_source_synced(_make_source_synced_payload())

    call_args = consumer._producer.send_and_wait.call_args
    emitted = call_args.kwargs["value"]
    assert emitted["chunks_processed"] == 0
    assert emitted["entities_upserted"] == 0
    assert emitted["relationships_upserted"] == 0


# ---------------------------------------------------------------------------
# AC-7: Kafka offset committed after every message regardless of outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_commits_offset_after_successful_message() -> None:
    consumer, *_ = _make_consumer()

    msg = _make_kafka_message(_SETTINGS.tombstone_topic, _make_tombstone_payload())

    async def _async_iter():
        yield msg  # generator exhausts after one message

    mock_kafka_consumer = AsyncMock()
    mock_kafka_consumer.__aiter__ = lambda self: _async_iter()
    consumer._consumer = mock_kafka_consumer
    consumer._running = True

    with patch.object(consumer, "_handle_message", new_callable=AsyncMock):
        await consumer.run()

    mock_kafka_consumer.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_commits_offset_after_failed_chunk_handling() -> None:
    """Offset must be committed even when extraction raises (exception is swallowed internally)."""
    consumer, mock_extractor, *_ = _make_consumer()
    # Extractor raises — _on_chunk_indexed will catch and swallow it
    mock_extractor.extract = AsyncMock(side_effect=RuntimeError("boom"))

    msg = _make_kafka_message(_SETTINGS.chunk_indexed_topic, _make_chunk_indexed_payload())

    async def _async_iter():
        yield msg  # generator exhausts after one message; no need to set _running

    mock_kafka_consumer = AsyncMock()
    mock_kafka_consumer.__aiter__ = lambda self: _async_iter()
    consumer._consumer = mock_kafka_consumer
    consumer._running = True

    await consumer.run()

    mock_kafka_consumer.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Unknown topic — warning logged, not raised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_unknown_topic_does_not_raise() -> None:
    consumer, *_ = _make_consumer()
    msg = _make_kafka_message("unknown.topic", {"foo": "bar"})
    # Should complete without raising
    await consumer._handle_message(msg)


# ---------------------------------------------------------------------------
# stop() gracefully stops consumer and producer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_stops_consumer_and_producer() -> None:
    consumer, *_ = _make_consumer()
    consumer._consumer = AsyncMock()
    consumer._producer = AsyncMock()
    consumer._running = True

    await consumer.stop()

    assert consumer._running is False
    consumer._consumer.stop.assert_awaited_once()
    consumer._producer.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_is_safe_when_not_started() -> None:
    consumer, *_ = _make_consumer()
    # Should not raise even if consumer/producer are None
    await consumer.stop()
    assert consumer._running is False


# ---------------------------------------------------------------------------
# TASK-US030-05 — named tests for AC acceptance checklist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tombstone_removes_entity_relationships() -> None:
    """AC-3 named check: tombstone routing deletes relationships and does NOT
    call merge_relationships."""
    consumer, _, _, _, mock_edge_store = _make_consumer()
    entity_id = "c" * 16
    msg = _make_kafka_message(
        _SETTINGS.tombstone_topic, _make_tombstone_payload(entity_id=entity_id)
    )

    with patch("src.knowledge_graph.updater.consumer.graph_tombstone_deletions_total"):
        await consumer._handle_message(msg)

    mock_edge_store.delete_entity_relationships.assert_awaited_once_with(entity_id)
    mock_edge_store.merge_relationships.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_relationships_expired_on_source_synced() -> None:
    """AC-5 named check: source.synced calls expire_stale_relationships with
    cutoff within 5 s of now - ttl_days."""
    consumer, _, _, _, mock_edge_store = _make_consumer()
    consumer._producer = AsyncMock()
    msg = _make_kafka_message(_SETTINGS.sync_topic, _make_source_synced_payload())

    with (
        patch("src.knowledge_graph.updater.consumer.graph_relationships_expired_total"),
        patch(
            "src.knowledge_graph.updater.consumer.graph_update_batch_duration_seconds"
        ) as mock_hist,
    ):
        mock_hist.labels.return_value = MagicMock()
        await consumer._handle_message(msg)

    mock_edge_store.expire_stale_relationships.assert_awaited_once()
    cutoff_arg = mock_edge_store.expire_stale_relationships.call_args.args[0]
    expected_cutoff = datetime.now(tz=UTC) - timedelta(days=_EXPIRY_SETTINGS.ttl_days)
    assert abs((cutoff_arg - expected_cutoff).total_seconds()) < 5


@pytest.mark.asyncio
async def test_graph_updated_event_emitted_after_source_synced() -> None:
    """AC-6 named check: source.synced emits knowledge.graph.updated with
    correct topic and event_type."""
    consumer, _, _, _, _ = _make_consumer()
    mock_producer = AsyncMock()
    consumer._producer = mock_producer
    msg = _make_kafka_message(_SETTINGS.sync_topic, _make_source_synced_payload())

    with (
        patch("src.knowledge_graph.updater.consumer.graph_relationships_expired_total"),
        patch(
            "src.knowledge_graph.updater.consumer.graph_update_batch_duration_seconds"
        ) as mock_hist,
    ):
        mock_hist.labels.return_value = MagicMock()
        await consumer._handle_message(msg)

    mock_producer.send_and_wait.assert_awaited_once()
    call_args = mock_producer.send_and_wait.call_args
    assert call_args.args[0] == _SETTINGS.graph_updated_topic
    payload = call_args.kwargs["value"]
    assert payload["event_type"] == "knowledge_graph_updated"
    assert str(payload["source_id"]) == str(_SOURCE_ID)
    assert "relationships_expired" in payload
