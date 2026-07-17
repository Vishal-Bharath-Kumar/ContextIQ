"""Tests for EntityConsumer — TASK-US028-04.

Covers all acceptance criteria using AsyncMock; no live Kafka or Neo4j in CI.
  AC-1  Consumer subscribes to both chunk_indexed and retry topics.
  AC-2  Successful extraction writes entities to Neo4j and increments success counter.
  AC-3  First failure re-queues to retry topic with attempt=2; retried counter incremented.
  AC-4  After max_retries failures, sends to DLQ; dead_lettered counter incremented; no more retries.
  AC-5  Retry topic message routes through _process_chunk with correct attempt number.
  AC-6  entity_extraction_duration_ms histogram observed on successful extraction.
  AC-7  Kafka offset committed after every message regardless of outcome.
  AC-8  run() raises RuntimeError when start() was not called.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.knowledge_graph.consumer import EntityConsumer, EntityConsumerSettings
from src.knowledge_graph.schemas.entity import (
    EntityExtractionResult,
    EntityType,
    ExtractedEntity,
    make_entity_id,
)
from src.knowledge_graph.schemas.events import ChunkIndexedEvent, ChunkRetryEnvelope

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CHUNK_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_SOURCE_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")
_NOW = datetime(2025, 1, 1, tzinfo=UTC)

_SETTINGS = EntityConsumerSettings(
    kafka_bootstrap_servers="localhost:9092",
    group_id="test-group",
    chunk_indexed_topic="knowledge.chunk.indexed",
    retry_topic="knowledge.chunk.indexed.retry",
    dead_letter_topic="knowledge.entity.extraction.dlq",
    max_retries=3,
    enable_auto_commit=False,
    max_poll_records=10,
)


def _make_event() -> ChunkIndexedEvent:
    return ChunkIndexedEvent(
        chunk_id=_CHUNK_ID,
        source_id=_SOURCE_ID,
        tenant_id="tenant-1",
        document_id="doc-1",
        text="Deploy auth service to production",
        token_count=10,
        embedding_model="text-embedding-3-small",
        indexed_at=_NOW,
    )


def _make_entity() -> ExtractedEntity:
    entity_type = EntityType.SERVICE
    canonical = "auth service"
    return ExtractedEntity(
        entity_id=make_entity_id(entity_type, canonical),
        entity_type=entity_type,
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
        duration_ms=120.0,
    )


def _make_consumer() -> tuple[EntityConsumer, AsyncMock, AsyncMock]:
    """Return (consumer, mock_extractor, mock_store) ready for use."""
    mock_extractor = MagicMock()
    mock_extractor._settings = MagicMock(model_id="gpt-4o-mini")
    mock_extractor.extract = AsyncMock(return_value=_make_extraction_result())

    mock_store = AsyncMock()

    consumer = EntityConsumer(
        extractor=mock_extractor,
        neo4j_store=mock_store,
        settings=_SETTINGS,
    )
    return consumer, mock_extractor, mock_store


def _make_kafka_message(topic: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(topic=topic, value=value)


# ---------------------------------------------------------------------------
# AC-8: start() guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_raises_if_start_not_called() -> None:
    consumer, _, _ = _make_consumer()
    with pytest.raises(RuntimeError, match="Call start()"):
        await consumer.run()


# ---------------------------------------------------------------------------
# AC-1: start() creates consumer subscribed to both topics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_subscribes_to_both_topics() -> None:
    consumer, _, _ = _make_consumer()

    mock_kafka_consumer = AsyncMock()
    mock_kafka_producer = AsyncMock()

    with (
        patch("src.knowledge_graph.consumer.AIOKafkaConsumer", return_value=mock_kafka_consumer),
        patch("src.knowledge_graph.consumer.AIOKafkaProducer", return_value=mock_kafka_producer),
    ):
        await consumer.start()

        from src.knowledge_graph.consumer import AIOKafkaConsumer

        AIOKafkaConsumer.assert_called_once()
        call_args = AIOKafkaConsumer.call_args
        assert _SETTINGS.chunk_indexed_topic in call_args.args
        assert _SETTINGS.retry_topic in call_args.args

        mock_kafka_consumer.start.assert_awaited_once()
        mock_kafka_producer.start.assert_awaited_once()
        assert consumer._running is True


# ---------------------------------------------------------------------------
# AC-2: Successful extraction writes to Neo4j and increments success counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_chunk_success_writes_entities_and_increments_counter() -> None:
    consumer, mock_extractor, mock_store = _make_consumer()
    event = _make_event()

    with patch("src.knowledge_graph.consumer.entity_extraction_total") as mock_counter, \
         patch("src.knowledge_graph.consumer.entity_extraction_duration_ms") as mock_hist, \
         patch("src.knowledge_graph.consumer.entities_extracted_total") as mock_ent_counter:
        mock_counter.labels.return_value = MagicMock()
        mock_hist.labels.return_value = MagicMock()
        mock_ent_counter.labels.return_value = MagicMock()

        await consumer._process_chunk(event, attempt=1)

    mock_extractor.extract.assert_awaited_once_with(event)
    mock_store.merge_entities.assert_awaited_once()
    entities_arg = mock_store.merge_entities.call_args.args[0]
    assert len(entities_arg) == 1
    assert entities_arg[0].entity_type == EntityType.SERVICE


@pytest.mark.asyncio
async def test_process_chunk_success_increments_success_counter() -> None:
    consumer, _, _ = _make_consumer()
    event = _make_event()

    with patch("src.knowledge_graph.consumer.entity_extraction_total") as mock_counter, \
         patch("src.knowledge_graph.consumer.entity_extraction_duration_ms") as mock_hist, \
         patch("src.knowledge_graph.consumer.entities_extracted_total") as mock_ent_counter:
        success_label = MagicMock()
        mock_counter.labels.return_value = success_label
        mock_hist.labels.return_value = MagicMock()
        mock_ent_counter.labels.return_value = MagicMock()

        await consumer._process_chunk(event, attempt=1)

    mock_counter.labels.assert_any_call(status="success")
    success_label.inc.assert_called()


# ---------------------------------------------------------------------------
# AC-6: Histogram observed on successful extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_chunk_success_observes_duration_histogram() -> None:
    consumer, _, _ = _make_consumer()
    event = _make_event()

    with patch("src.knowledge_graph.consumer.entity_extraction_duration_ms") as mock_hist, \
         patch("src.knowledge_graph.consumer.entity_extraction_total") as mock_counter, \
         patch("src.knowledge_graph.consumer.entities_extracted_total") as mock_ent_counter:
        hist_label = MagicMock()
        mock_hist.labels.return_value = hist_label
        mock_counter.labels.return_value = MagicMock()
        mock_ent_counter.labels.return_value = MagicMock()

        await consumer._process_chunk(event, attempt=1)

    mock_hist.labels.assert_called_once_with(model_id="gpt-4o-mini")
    hist_label.observe.assert_called_once_with(120.0)


# ---------------------------------------------------------------------------
# AC-3: First failure re-queues with attempt+1; retried counter incremented
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_chunk_failure_requeues_on_first_attempt() -> None:
    consumer, mock_extractor, _ = _make_consumer()
    mock_extractor.extract = AsyncMock(side_effect=ValueError("LLM error"))
    event = _make_event()

    mock_producer = AsyncMock()
    consumer._producer = mock_producer

    with patch("src.knowledge_graph.consumer.entity_extraction_total") as mock_counter:
        retried_label = MagicMock()
        mock_counter.labels.return_value = retried_label

        await consumer._process_chunk(event, attempt=1)

    # Sent to retry topic, not DLQ
    mock_producer.send_and_wait.assert_awaited_once()
    call_args = mock_producer.send_and_wait.call_args
    assert call_args.args[0] == _SETTINGS.retry_topic
    envelope = call_args.kwargs["value"]
    assert envelope["attempt"] == 2

    mock_counter.labels.assert_any_call(status="retried")
    retried_label.inc.assert_called()


@pytest.mark.asyncio
async def test_process_chunk_failure_does_not_send_to_dlq_before_max_retries() -> None:
    consumer, mock_extractor, _ = _make_consumer()
    mock_extractor.extract = AsyncMock(side_effect=RuntimeError("boom"))
    event = _make_event()

    mock_producer = AsyncMock()
    consumer._producer = mock_producer

    with patch("src.knowledge_graph.consumer.entity_extraction_total"):
        # attempt=2, max_retries=3 — still below threshold
        await consumer._process_chunk(event, attempt=2)

    call_args = mock_producer.send_and_wait.call_args
    assert call_args.args[0] == _SETTINGS.retry_topic


# ---------------------------------------------------------------------------
# AC-4: After max_retries failures, sent to DLQ; no further retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_chunk_sends_to_dlq_after_max_retries() -> None:
    consumer, mock_extractor, _ = _make_consumer()
    mock_extractor.extract = AsyncMock(side_effect=ValueError("permanent error"))
    event = _make_event()

    mock_producer = AsyncMock()
    consumer._producer = mock_producer

    with patch("src.knowledge_graph.consumer.entity_extraction_total") as mock_counter:
        dlq_label = MagicMock()
        mock_counter.labels.return_value = dlq_label

        # attempt == max_retries (3) — exhausted
        await consumer._process_chunk(event, attempt=3)

    mock_producer.send_and_wait.assert_awaited_once()
    call_args = mock_producer.send_and_wait.call_args
    assert call_args.args[0] == _SETTINGS.dead_letter_topic

    mock_counter.labels.assert_any_call(status="dead_lettered")
    dlq_label.inc.assert_called()


# ---------------------------------------------------------------------------
# AC-5: Retry topic message routes with correct attempt number
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_retry_topic_passes_attempt_from_envelope() -> None:
    consumer, mock_extractor, mock_store = _make_consumer()
    event = _make_event()
    envelope = ChunkRetryEnvelope(attempt=2, original=event)
    msg = _make_kafka_message(_SETTINGS.retry_topic, envelope.model_dump())

    with patch.object(consumer, "_process_chunk", new=AsyncMock()) as mock_process:
        await consumer._handle_message(msg)

    mock_process.assert_awaited_once()
    # attempt is passed as keyword argument
    assert mock_process.call_args.kwargs["attempt"] == 2

@pytest.mark.asyncio
async def test_handle_message_primary_topic_starts_at_attempt_1() -> None:
    consumer, _, _ = _make_consumer()
    event = _make_event()
    msg = _make_kafka_message(_SETTINGS.chunk_indexed_topic, event.model_dump())

    with patch.object(consumer, "_process_chunk", new=AsyncMock()) as mock_process:
        await consumer._handle_message(msg)

    assert mock_process.call_args.kwargs["attempt"] == 1


# ---------------------------------------------------------------------------
# AC-7: Offset committed after every message regardless of outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_commits_offset_on_success() -> None:
    consumer, _, _ = _make_consumer()
    event = _make_event()
    msg = _make_kafka_message(_SETTINGS.chunk_indexed_topic, event.model_dump())

    mock_kafka_consumer = AsyncMock()
    # Yield one message then stop the loop
    async def _aiter(_) -> object:  # noqa: ANN001
        yield msg
        consumer._running = False

    mock_kafka_consumer.__aiter__ = _aiter
    mock_kafka_consumer.commit = AsyncMock()
    consumer._consumer = mock_kafka_consumer
    consumer._running = True

    with patch.object(consumer, "_handle_message", new=AsyncMock()):
        await consumer.run()

    mock_kafka_consumer.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_commits_offset_on_failure() -> None:
    consumer, mock_extractor, _ = _make_consumer()
    mock_extractor.extract = AsyncMock(side_effect=ValueError("fail"))

    event = _make_event()
    msg = _make_kafka_message(_SETTINGS.chunk_indexed_topic, event.model_dump())

    mock_kafka_consumer = AsyncMock()

    async def _aiter(_) -> object:  # noqa: ANN001
        yield msg
        consumer._running = False

    mock_kafka_consumer.__aiter__ = _aiter
    mock_kafka_consumer.commit = AsyncMock()
    consumer._consumer = mock_kafka_consumer
    consumer._producer = AsyncMock()
    consumer._running = True

    with patch("src.knowledge_graph.consumer.entity_extraction_total"):
        await consumer.run()

    mock_kafka_consumer.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# stop() cleans up consumer and producer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_stops_consumer_and_producer() -> None:
    consumer, _, _ = _make_consumer()
    mock_kafka_consumer = AsyncMock()
    mock_kafka_producer = AsyncMock()
    consumer._consumer = mock_kafka_consumer
    consumer._producer = mock_kafka_producer
    consumer._running = True

    await consumer.stop()

    assert consumer._running is False
    mock_kafka_consumer.stop.assert_awaited_once()
    mock_kafka_producer.stop.assert_awaited_once()
