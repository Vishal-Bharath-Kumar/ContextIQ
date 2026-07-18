"""Unit tests for TASK-US013-05 — SourceSyncEventConsumer.

All tests mock AIOKafkaConsumer; no live Kafka broker is required.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.retrieval.cache.sync_event_consumer import SourceSyncEventConsumer
from src.retrieval.cache.sync_event_schema import SourceSyncEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs) -> SourceSyncEvent:
    defaults = {
        "event_id": "evt-0001",
        "source_id": "github",
        "sync_type": "full",
        "timestamp": "2024-01-01T12:00:00Z",
        "doc_count": 42,
    }
    return SourceSyncEvent(**{**defaults, **kwargs})


def _make_kafka_msg(event: SourceSyncEvent, partition: int = 0, offset: int = 0):
    msg = MagicMock()
    msg.value = event.model_dump()
    msg.partition = partition
    msg.offset = offset
    return msg


async def _async_iter(items) -> AsyncIterator:
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# SourceSyncEvent schema
# ---------------------------------------------------------------------------


class TestSourceSyncEvent:
    def test_valid_event(self):
        data = {
            "event_id": "abc-123",
            "source_id": "confluence",
            "sync_type": "incremental",
            "timestamp": "2024-06-01T08:30:00Z",
            "doc_count": 5,
        }
        event = SourceSyncEvent.model_validate(data)
        assert event.source_id == "confluence"
        assert event.sync_type == "incremental"
        assert event.doc_count == 5

    def test_missing_field_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SourceSyncEvent.model_validate({"event_id": "x"})


# ---------------------------------------------------------------------------
# Consumer start / stop
# ---------------------------------------------------------------------------


class TestConsumerLifecycle:
    @pytest.fixture
    def mock_kafka_cls(self):
        with patch("src.retrieval.cache.sync_event_consumer.AIOKafkaConsumer") as cls:
            instance = AsyncMock()
            cls.return_value = instance
            yield cls, instance

    @pytest.fixture
    def cache(self):
        c = AsyncMock()
        c.invalidate_source = AsyncMock(return_value=3)
        return c

    def test_consumer_group_and_topic_constants(self):
        assert SourceSyncEventConsumer.TOPIC == "contextiq.source.sync"
        assert SourceSyncEventConsumer.CONSUMER_GROUP == "context-cache-invalidator"

    async def test_start_calls_kafka_start(self, mock_kafka_cls, cache):
        _, kafka_instance = mock_kafka_cls
        consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
        await consumer.start()
        kafka_instance.start.assert_awaited_once()

    async def test_stop_calls_kafka_stop(self, mock_kafka_cls, cache):
        _, kafka_instance = mock_kafka_cls
        consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
        await consumer.stop()
        kafka_instance.stop.assert_awaited_once()

    def test_constructor_passes_bootstrap_servers(self, mock_kafka_cls, cache):
        cls, _ = mock_kafka_cls
        SourceSyncEventConsumer(cache=cache, bootstrap_servers="broker1:9092")
        call_kwargs = cls.call_args
        assert call_kwargs.kwargs.get("bootstrap_servers") == "broker1:9092" or \
               call_kwargs.args[1] == "broker1:9092"

    def test_constructor_disables_auto_commit(self, mock_kafka_cls, cache):
        cls, _ = mock_kafka_cls
        SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
        call_kwargs = cls.call_args.kwargs
        assert call_kwargs.get("enable_auto_commit") is False

    def test_constructor_sets_consumer_group(self, mock_kafka_cls, cache):
        cls, _ = mock_kafka_cls
        SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
        call_kwargs = cls.call_args.kwargs
        assert call_kwargs.get("group_id") == SourceSyncEventConsumer.CONSUMER_GROUP


# ---------------------------------------------------------------------------
# consume() — happy path
# ---------------------------------------------------------------------------


class TestConsume:
    @pytest.fixture
    def cache(self):
        c = AsyncMock()
        c.invalidate_source = AsyncMock(return_value=7)
        return c

    async def test_invalidates_source_on_valid_event(self, cache):
        event = _make_event(source_id="github")
        msg = _make_kafka_msg(event)

        mock_kafka = AsyncMock()
        mock_kafka.__aiter__ = MagicMock(return_value=_async_iter([msg]))
        mock_kafka.commit = AsyncMock()

        with patch(
            "src.retrieval.cache.sync_event_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
            # Run until no more messages
            await asyncio.wait_for(consumer.consume(), timeout=1.0)

        cache.invalidate_source.assert_awaited_once_with("github")

    async def test_commits_after_successful_invalidation(self, cache):
        event = _make_event(source_id="confluence")
        msg = _make_kafka_msg(event)

        mock_kafka = AsyncMock()
        mock_kafka.__aiter__ = MagicMock(return_value=_async_iter([msg]))
        mock_kafka.commit = AsyncMock()

        with patch(
            "src.retrieval.cache.sync_event_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
            await asyncio.wait_for(consumer.consume(), timeout=1.0)

        mock_kafka.commit.assert_awaited_once()

    async def test_commit_not_called_when_invalidation_raises(self, cache):
        """Offset must NOT be committed if invalidate_source fails."""
        cache.invalidate_source.side_effect = RuntimeError("redis down")
        event = _make_event()
        msg = _make_kafka_msg(event)

        mock_kafka = AsyncMock()
        mock_kafka.__aiter__ = MagicMock(return_value=_async_iter([msg]))
        mock_kafka.commit = AsyncMock()

        with patch(
            "src.retrieval.cache.sync_event_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
            await asyncio.wait_for(consumer.consume(), timeout=1.0)

        mock_kafka.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# consume() — poison-pill / malformed messages
# ---------------------------------------------------------------------------


class TestConsumeMalformedMessages:
    @pytest.fixture
    def cache(self):
        c = AsyncMock()
        c.invalidate_source = AsyncMock(return_value=0)
        return c

    async def test_skips_malformed_message_and_continues(self, cache):
        """Consumer must NOT crash when a message fails Pydantic validation."""
        bad_msg = MagicMock()
        bad_msg.value = {"not_a_valid": "event"}
        bad_msg.partition = 0
        bad_msg.offset = 0

        good_event = _make_event(source_id="jira")
        good_msg = _make_kafka_msg(good_event)

        mock_kafka = AsyncMock()
        mock_kafka.__aiter__ = MagicMock(
            return_value=_async_iter([bad_msg, good_msg])
        )
        mock_kafka.commit = AsyncMock()

        with patch(
            "src.retrieval.cache.sync_event_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
            await asyncio.wait_for(consumer.consume(), timeout=1.0)

        # The good message must still be processed
        cache.invalidate_source.assert_awaited_once_with("jira")

    async def test_no_crash_on_json_decode_error(self, cache):
        """Malformed JSON payload is caught; consumer continues."""
        bad_msg = MagicMock()
        bad_msg.value = "not-a-dict"
        bad_msg.partition = 0
        bad_msg.offset = 1

        mock_kafka = AsyncMock()
        mock_kafka.__aiter__ = MagicMock(return_value=_async_iter([bad_msg]))
        mock_kafka.commit = AsyncMock()

        with patch(
            "src.retrieval.cache.sync_event_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
            # Should complete without raising
            await asyncio.wait_for(consumer.consume(), timeout=1.0)

        cache.invalidate_source.assert_not_awaited()


# ---------------------------------------------------------------------------
# consume() — CancelledError propagates (clean shutdown)
# ---------------------------------------------------------------------------


class TestConsumeCancellation:
    async def test_cancelled_error_propagates(self):
        """asyncio.CancelledError must not be swallowed — allows clean task teardown."""
        cache = AsyncMock()
        cache.invalidate_source = AsyncMock(side_effect=asyncio.CancelledError())

        event = _make_event()
        msg = _make_kafka_msg(event)

        mock_kafka = AsyncMock()
        mock_kafka.__aiter__ = MagicMock(return_value=_async_iter([msg]))
        mock_kafka.commit = AsyncMock()

        with patch(
            "src.retrieval.cache.sync_event_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            consumer = SourceSyncEventConsumer(cache=cache, bootstrap_servers="b:9092")
            with pytest.raises(asyncio.CancelledError):
                await consumer.consume()
