"""Unit tests for IndexingPipeline and IndexingConsumer — TASK-US027-04.

All tests run without live Kafka, Qdrant, OpenSearch, or PostgreSQL:
  - AIOKafkaConsumer is mocked via AsyncMock / MagicMock.
  - All store/repo dependencies use AsyncMock.
  - IndexingPipeline is exercised independently of the Kafka consumer.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from src.indexing.consumer import IndexingConsumer, IndexingConsumerSettings
from src.indexing.pipeline import IndexingPipeline
from src.indexing.schemas.chunk import ChunkPayload, IndexedChunk
from src.indexing.schemas.events import DocumentDeletedEvent, SourceSyncedEvent

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SOURCE_ID = uuid4()
TENANT_ID = "acme"
JOB_ID = uuid4()
DOC_ID = "doc:42"


def _make_chunk(i: int = 0) -> ChunkPayload:
    return ChunkPayload(
        source_id=SOURCE_ID,
        tenant_id=TENANT_ID,
        document_id=DOC_ID,
        text=f"chunk text {i}",
        token_count=3,
    )


def _make_indexed(chunk: ChunkPayload) -> IndexedChunk:
    return IndexedChunk(payload=chunk, vector=[0.1, 0.2], model_id="test-model")


def _pipeline_mocks() -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock, MagicMock]:
    """Return (embedder, qdrant, opensearch, chunk_repo, registry) mocks."""
    embedder = AsyncMock()
    qdrant = AsyncMock()
    opensearch = AsyncMock()
    chunk_repo = AsyncMock()
    registry = MagicMock()
    return embedder, qdrant, opensearch, chunk_repo, registry


# ---------------------------------------------------------------------------
# IndexingPipeline
# ---------------------------------------------------------------------------


class TestIndexingPipeline:
    """Tests for IndexingPipeline.run_for_source."""

    def _build(
        self,
        chunks: list[ChunkPayload],
        indexed: list[IndexedChunk] | None = None,
    ) -> tuple[IndexingPipeline, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
        embedder, qdrant, opensearch, chunk_repo, registry = _pipeline_mocks()

        connector = AsyncMock()
        connector.get_chunks = AsyncMock(return_value=chunks)
        registry.get.return_value = connector

        indexed_chunks = indexed if indexed is not None else [_make_indexed(c) for c in chunks]
        embedder.embed_batch = AsyncMock(return_value=indexed_chunks)

        pipeline = IndexingPipeline(
            embedder=embedder,
            qdrant=qdrant,
            opensearch=opensearch,
            chunk_repo=chunk_repo,
            registry=registry,
        )
        return pipeline, embedder, qdrant, opensearch, chunk_repo

    @pytest.mark.asyncio
    async def test_returns_chunk_count(self) -> None:
        chunks = [_make_chunk(i) for i in range(5)]
        pipeline, *_ = self._build(chunks)

        result = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        assert result == 5

    @pytest.mark.asyncio
    async def test_ensure_collection_and_index_called_concurrently(self) -> None:
        """ensure_collection and ensure_index must be called (AC-6 concurrent setup)."""
        chunks = [_make_chunk()]
        pipeline, _, qdrant, opensearch, _ = self._build(chunks)

        await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        qdrant.ensure_collection.assert_awaited_once_with(SOURCE_ID, TENANT_ID)
        opensearch.ensure_index.assert_awaited_once_with(TENANT_ID)

    @pytest.mark.asyncio
    async def test_upsert_and_bulk_index_called_concurrently(self) -> None:
        """qdrant.upsert and opensearch.bulk_index must both be called (AC-6)."""
        chunks = [_make_chunk()]
        indexed = [_make_indexed(chunks[0])]
        pipeline, _, qdrant, opensearch, _ = self._build(chunks, indexed)

        await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        qdrant.upsert.assert_awaited_once_with(indexed, SOURCE_ID, TENANT_ID)
        opensearch.bulk_index.assert_awaited_once_with(indexed, tenant_id=TENANT_ID)

    @pytest.mark.asyncio
    async def test_chunk_repo_upsert_batch_called_with_metadata(self) -> None:
        """chunk_repo.upsert_batch is called with correct ChunkMetadata (AC-5)."""
        chunk = _make_chunk()
        indexed = [_make_indexed(chunk)]
        pipeline, _, _, _, chunk_repo = self._build([chunk], indexed)

        await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        chunk_repo.upsert_batch.assert_awaited_once()
        metadata_list = chunk_repo.upsert_batch.call_args[0][0]
        assert len(metadata_list) == 1
        meta = metadata_list[0]
        assert meta.chunk_id == chunk.chunk_id
        assert meta.source_id == SOURCE_ID
        assert meta.tenant_id == TENANT_ID
        assert meta.document_id == DOC_ID
        assert meta.embedding_model == "test-model"
        assert meta.token_count == chunk.token_count

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_zero(self) -> None:
        """An empty chunk list short-circuits the pipeline and returns 0."""
        pipeline, embedder, qdrant, opensearch, chunk_repo = self._build([])
        # embed_batch returns [] for empty input — patch to simulate that
        embedder.embed_batch = AsyncMock(return_value=[])

        result = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        assert result == 0
        chunk_repo.upsert_batch.assert_awaited_once_with([])

    @pytest.mark.asyncio
    async def test_registry_queried_with_string_source_id(self) -> None:
        """Registry.get is called with the string representation of source_id."""
        chunks = [_make_chunk()]
        pipeline, _, _, _, _ = self._build(chunks)

        # Access the registry mock via the pipeline
        await pipeline.run_for_source(SOURCE_ID, TENANT_ID)
        pipeline._registry.get.assert_called_once_with(str(SOURCE_ID))


# ---------------------------------------------------------------------------
# IndexingConsumer — _handle_message
# ---------------------------------------------------------------------------


class TestIndexingConsumerHandleMessage:
    """Tests for IndexingConsumer._handle_message routing logic."""

    def _build_consumer(self) -> tuple[IndexingConsumer, AsyncMock, AsyncMock]:
        pipeline = AsyncMock(spec=IndexingPipeline)
        pipeline.run_for_source = AsyncMock(return_value=3)
        deletion_handler = AsyncMock()

        settings = IndexingConsumerSettings.model_construct(
            kafka_bootstrap_servers="localhost:9092",
            group_id="test-group",
            sync_topic="knowledge.source.synced",
            deletion_topic="knowledge.document.deleted",
            max_poll_records=100,
            poll_timeout_ms=1000,
            enable_auto_commit=False,
        )
        consumer = IndexingConsumer(
            pipeline=pipeline,
            deletion_handler=deletion_handler,
            settings=settings,
        )
        return consumer, pipeline, deletion_handler

    def _make_msg(self, payload: dict) -> MagicMock:
        msg = MagicMock()
        msg.value = payload
        return msg

    @pytest.mark.asyncio
    async def test_synced_event_routes_to_pipeline(self) -> None:
        """knowledge_source_synced triggers pipeline.run_for_source (AC-1)."""
        consumer, pipeline, _ = self._build_consumer()
        msg = self._make_msg(
            {
                "event_type": "knowledge_source_synced",
                "source_id": str(SOURCE_ID),
                "tenant_id": TENANT_ID,
                "job_id": str(JOB_ID),
                "items_processed": 10,
                "synced_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )

        await consumer._handle_message(msg)

        pipeline.run_for_source.assert_awaited_once_with(
            source_id=SOURCE_ID,
            tenant_id=TENANT_ID,
        )

    @pytest.mark.asyncio
    async def test_deleted_event_routes_to_deletion_handler(self) -> None:
        """knowledge_document_deleted triggers deletion_handler.handle (AC-7)."""
        consumer, _, deletion_handler = self._build_consumer()
        msg = self._make_msg(
            {
                "event_type": "knowledge_document_deleted",
                "source_id": str(SOURCE_ID),
                "tenant_id": TENANT_ID,
                "document_id": DOC_ID,
            }
        )

        await consumer._handle_message(msg)

        deletion_handler.handle.assert_awaited_once_with(
            document_id=DOC_ID,
            source_id=SOURCE_ID,
            tenant_id=TENANT_ID,
        )

    @pytest.mark.asyncio
    async def test_unknown_event_type_skipped_without_exception(self) -> None:
        """Unknown event_type is logged and skipped — consumer loop must not crash."""
        consumer, pipeline, deletion_handler = self._build_consumer()
        msg = self._make_msg({"event_type": "some_unknown_event", "data": "x"})

        # Must not raise
        await consumer._handle_message(msg)

        pipeline.run_for_source.assert_not_awaited()
        deletion_handler.handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_in_handler_is_caught_and_skipped(self) -> None:
        """Exceptions during processing are caught so the loop survives (poison-pill)."""
        consumer, pipeline, _ = self._build_consumer()
        pipeline.run_for_source.side_effect = RuntimeError("store unavailable")

        msg = self._make_msg(
            {
                "event_type": "knowledge_source_synced",
                "source_id": str(SOURCE_ID),
                "tenant_id": TENANT_ID,
                "job_id": str(JOB_ID),
                "items_processed": 5,
                "synced_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )

        # Must not raise even though the pipeline threw
        await consumer._handle_message(msg)


# ---------------------------------------------------------------------------
# IndexingConsumer — start / stop / run
# ---------------------------------------------------------------------------


class TestIndexingConsumerLifecycle:
    """Tests for IndexingConsumer start/stop/run lifecycle using a mock broker."""

    def _build_consumer(self) -> tuple[IndexingConsumer, AsyncMock, AsyncMock]:
        pipeline = AsyncMock(spec=IndexingPipeline)
        pipeline.run_for_source = AsyncMock(return_value=0)
        deletion_handler = AsyncMock()

        settings = IndexingConsumerSettings.model_construct(
            kafka_bootstrap_servers="localhost:9092",
            group_id="test-group",
            sync_topic="knowledge.source.synced",
            deletion_topic="knowledge.document.deleted",
            max_poll_records=10,
            poll_timeout_ms=500,
            enable_auto_commit=False,
        )
        consumer = IndexingConsumer(
            pipeline=pipeline,
            deletion_handler=deletion_handler,
            settings=settings,
        )
        return consumer, pipeline, deletion_handler

    @pytest.mark.asyncio
    async def test_run_before_start_raises(self) -> None:
        """Calling run() before start() must raise RuntimeError."""
        consumer, _, _ = self._build_consumer()
        with pytest.raises(RuntimeError, match="start()"):
            await consumer.run()

    @pytest.mark.asyncio
    async def test_start_creates_and_starts_kafka_consumer(self) -> None:
        """start() creates AIOKafkaConsumer and calls its start() method."""
        consumer, _, _ = self._build_consumer()
        mock_kafka = AsyncMock()

        with patch("src.indexing.consumer.AIOKafkaConsumer", return_value=mock_kafka):
            await consumer.start()

        mock_kafka.start.assert_awaited_once()
        assert consumer._running is True

    @pytest.mark.asyncio
    async def test_stop_sets_running_false_and_stops_kafka(self) -> None:
        """stop() sets _running=False and stops the underlying Kafka consumer."""
        consumer, _, _ = self._build_consumer()
        mock_kafka = AsyncMock()

        with patch("src.indexing.consumer.AIOKafkaConsumer", return_value=mock_kafka):
            await consumer.start()
            await consumer.stop()

        assert consumer._running is False
        mock_kafka.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_commits_after_each_message(self) -> None:
        """Offset is committed after every successful _handle_message call (at-least-once)."""
        consumer, _, _ = self._build_consumer()
        mock_kafka = AsyncMock()

        synced_payload = {
            "event_type": "knowledge_source_synced",
            "source_id": str(SOURCE_ID),
            "tenant_id": TENANT_ID,
            "job_id": str(JOB_ID),
            "items_processed": 1,
            "synced_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        msg1 = MagicMock()
        msg1.value = synced_payload
        msg2 = MagicMock()
        msg2.value = synced_payload

        # Simulate two messages then stop
        async def _aiter(self_inner):  # noqa: ANN001
            yield msg1
            yield msg2

        mock_kafka.__aiter__ = _aiter

        with patch("src.indexing.consumer.AIOKafkaConsumer", return_value=mock_kafka):
            await consumer.start()
            await consumer.run()

        assert mock_kafka.commit.await_count == 2

    @pytest.mark.asyncio
    async def test_run_subscribes_to_both_topics(self) -> None:
        """AIOKafkaConsumer must be constructed with both topics (AC-1)."""
        consumer, _, _ = self._build_consumer()
        mock_kafka = AsyncMock()

        async def _empty_aiter():
            return
            yield  # make it an async generator

        mock_kafka.__aiter__ = lambda self_inner: _empty_aiter()

        with patch(
            "src.indexing.consumer.AIOKafkaConsumer", return_value=mock_kafka
        ) as mock_cls:
            await consumer.start()
            # _running is True; the empty async iterator exits immediately
            await consumer.run()

        call_args = mock_cls.call_args
        positional_topics = call_args[0]
        assert "knowledge.source.synced" in positional_topics
        assert "knowledge.document.deleted" in positional_topics
