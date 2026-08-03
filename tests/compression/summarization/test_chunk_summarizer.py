"""Unit tests for ChunkSummarizer (TASK-US017-04)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.compression.summarization.chain import SummarizationChain, SummarizationOutput
from src.compression.summarization.chunk_summarizer import ChunkSummarizer
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUMMARY_OUTPUT = SummarizationOutput(
    summary="Concise compressed summary of the chunk.",
    retained_entities=["entity-A", "entity-B"],
)


def _make_chunk(content: str, chunk_id: str = "a1b2c3d4e5f60001") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id="test-src",
        content=content,
        score=0.85,
        metadata=ChunkMetadata(
            file_path="/docs/test.md",
            timestamp=datetime(2025, 1, 1),
            author="tester",
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.token_threshold = 100
    settings.max_concurrent = 5
    return settings


@pytest.fixture
def mock_chain() -> MagicMock:
    chain = MagicMock(spec=SummarizationChain)
    chain.summarise = AsyncMock(return_value=_SUMMARY_OUTPUT)
    return chain


@pytest.fixture
def summarizer(mock_chain: MagicMock, mock_settings: MagicMock) -> ChunkSummarizer:
    with patch(
        "src.compression.summarization.chunk_summarizer.get_summarization_settings",
        return_value=mock_settings,
    ):
        return ChunkSummarizer(chain=mock_chain)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestChunkSummarizerInit:
    def test_default_chain_created_when_none(self, mock_settings: MagicMock) -> None:
        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            with patch(
                "src.compression.summarization.chunk_summarizer.SummarizationChain"
            ) as mock_chain_cls:
                ChunkSummarizer()
                mock_chain_cls.assert_called_once()

    def test_custom_chain_is_used(self, mock_chain: MagicMock, mock_settings: MagicMock) -> None:
        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=mock_chain)
            assert s._chain is mock_chain

    def test_callbacks_default_empty(self, mock_chain: MagicMock, mock_settings: MagicMock) -> None:
        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=mock_chain)
            assert s._callbacks == []

    def test_custom_callbacks_stored(self, mock_chain: MagicMock, mock_settings: MagicMock) -> None:
        cbs = [MagicMock()]
        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=mock_chain, callbacks=cbs)
            assert s._callbacks is cbs


# ---------------------------------------------------------------------------
# summarize() — core behaviour
# ---------------------------------------------------------------------------


class TestChunkSummarizerSummarize:
    async def test_empty_list_returns_empty(self, summarizer: ChunkSummarizer) -> None:
        result = await summarizer.summarize([])
        assert result == []

    async def test_sub_threshold_chunk_unchanged(
        self, summarizer: ChunkSummarizer, mock_chain: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.token_threshold = 100
        chunk = _make_chunk("short content")
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=50,
        ):
            result = await summarizer.summarize([chunk])

        assert result == [chunk]
        mock_chain.summarise.assert_not_called()

    async def test_sub_threshold_compressed_flag_false(
        self, summarizer: ChunkSummarizer, mock_settings: MagicMock
    ) -> None:
        mock_settings.token_threshold = 100
        chunk = _make_chunk("short content")
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=50,
        ):
            result = await summarizer.summarize([chunk])

        assert result[0].compressed is False
        assert result[0].original_token_count is None

    async def test_above_threshold_compressed_true(
        self, summarizer: ChunkSummarizer, mock_settings: MagicMock
    ) -> None:
        mock_settings.token_threshold = 100
        chunk = _make_chunk("long content " * 50)
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=200,
        ):
            result = await summarizer.summarize([chunk])

        assert result[0].compressed is True

    async def test_above_threshold_original_token_count_set(
        self, summarizer: ChunkSummarizer, mock_settings: MagicMock
    ) -> None:
        mock_settings.token_threshold = 100
        chunk = _make_chunk("long content " * 50)
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=200,
        ):
            result = await summarizer.summarize([chunk])

        assert result[0].original_token_count == 200

    async def test_above_threshold_content_replaced_by_summary(
        self, summarizer: ChunkSummarizer, mock_settings: MagicMock
    ) -> None:
        mock_settings.token_threshold = 100
        chunk = _make_chunk("long content " * 50)
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=200,
        ):
            result = await summarizer.summarize([chunk])

        assert result[0].content == _SUMMARY_OUTPUT.summary

    async def test_order_preserved_for_mixed_chunks(
        self, summarizer: ChunkSummarizer, mock_settings: MagicMock
    ) -> None:
        """Even-indexed chunks are above threshold; odd-indexed are below."""
        mock_settings.token_threshold = 100
        chunks = [_make_chunk(f"chunk{i}", chunk_id=f"{i:016x}") for i in range(6)]

        def _token_side_effect(content: str) -> int:
            idx = int(content.replace("chunk", ""))
            return 200 if idx % 2 == 0 else 50

        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            side_effect=_token_side_effect,
        ):
            result = await summarizer.summarize(chunks)

        assert len(result) == 6
        for i, chunk in enumerate(result):
            if i % 2 == 0:
                assert chunk.compressed is True, f"chunk {i} should be compressed"
            else:
                assert chunk.compressed is False, f"chunk {i} should be unchanged"

    async def test_callbacks_forwarded_to_chain(
        self, mock_chain: MagicMock, mock_settings: MagicMock
    ) -> None:
        cbs = [MagicMock()]
        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=mock_chain, callbacks=cbs)

        chunk = _make_chunk("long content")
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=200,
        ):
            await s.summarize([chunk])

        _, kwargs = mock_chain.summarise.call_args
        assert kwargs["callbacks"] is cbs


# ---------------------------------------------------------------------------
# Fail-open behaviour
# ---------------------------------------------------------------------------


class TestChunkSummarizerFailOpen:
    async def test_llm_error_returns_original_chunk(self, mock_settings: MagicMock) -> None:
        mock_settings.token_threshold = 100
        failing_chain = MagicMock(spec=SummarizationChain)
        failing_chain.summarise = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=failing_chain)

        chunk = _make_chunk("long content " * 50)
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=200,
        ):
            result = await s.summarize([chunk])

        assert result == [chunk]
        assert result[0].compressed is False

    async def test_no_exception_propagates_on_llm_error(self, mock_settings: MagicMock) -> None:
        mock_settings.token_threshold = 100
        failing_chain = MagicMock(spec=SummarizationChain)
        failing_chain.summarise = AsyncMock(side_effect=Exception("any error"))

        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=failing_chain)

        chunk = _make_chunk("long content")
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=200,
        ):
            result = await s.summarize([chunk])

        assert len(result) == 1

    async def test_one_failure_does_not_block_other_chunks(self, mock_settings: MagicMock) -> None:
        """Chunk that fails summarisation returns original; others are still compressed."""
        mock_settings.token_threshold = 100

        async def _side_effect(content: str, input_tokens: int, callbacks: list) -> SummarizationOutput:
            if content == "chunk_fail":
                raise ValueError("Intentional failure")
            return _SUMMARY_OUTPUT

        chain = MagicMock(spec=SummarizationChain)
        chain.summarise = AsyncMock(side_effect=_side_effect)

        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=chain)

        chunks = [
            _make_chunk("chunk_fail", chunk_id="0" * 16),
            _make_chunk("chunk_ok_1", chunk_id="1" + "0" * 15),
            _make_chunk("chunk_ok_2", chunk_id="2" + "0" * 15),
        ]
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=200,
        ):
            result = await s.summarize(chunks)

        assert result[0].compressed is False
        assert result[0].content == "chunk_fail"
        assert result[1].compressed is True
        assert result[2].compressed is True


# ---------------------------------------------------------------------------
# Semaphore / concurrency
# ---------------------------------------------------------------------------


class TestChunkSummarizerSemaphore:
    async def test_semaphore_initialised_with_max_concurrent(self, mock_settings: MagicMock) -> None:
        mock_settings.token_threshold = 10
        mock_settings.max_concurrent = 3

        mock_chain = MagicMock(spec=SummarizationChain)
        mock_chain.summarise = AsyncMock(return_value=_SUMMARY_OUTPUT)

        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            with patch(
                "src.compression.summarization.chunk_summarizer.asyncio.Semaphore",
                wraps=asyncio.Semaphore,
            ) as mock_sem_cls:
                s = ChunkSummarizer(chain=mock_chain)
                chunks = [_make_chunk("text", chunk_id=f"{i:016x}") for i in range(3)]
                with patch(
                    "src.compression.summarization.chunk_summarizer.count_tokens",
                    return_value=100,
                ):
                    await s.summarize(chunks)

        mock_sem_cls.assert_called_once_with(3)

    async def test_max_concurrent_respected(self, mock_settings: MagicMock) -> None:
        """Active in-flight LLM calls never exceed max_concurrent."""
        max_concurrent = 2
        mock_settings.token_threshold = 10
        mock_settings.max_concurrent = max_concurrent

        active = 0
        max_observed = 0

        async def _counting_summarise(
            content: str, input_tokens: int, callbacks: list
        ) -> SummarizationOutput:
            nonlocal active, max_observed
            active += 1
            if active > max_observed:
                max_observed = active
            await asyncio.sleep(0.002)
            active -= 1
            return SummarizationOutput(summary="s", retained_entities=[])

        chain = MagicMock(spec=SummarizationChain)
        chain.summarise = AsyncMock(side_effect=_counting_summarise)

        with patch(
            "src.compression.summarization.chunk_summarizer.get_summarization_settings",
            return_value=mock_settings,
        ):
            s = ChunkSummarizer(chain=chain)

        chunks = [_make_chunk(f"long-{i}", chunk_id=f"{i:016x}") for i in range(8)]
        with patch(
            "src.compression.summarization.chunk_summarizer.count_tokens",
            return_value=100,
        ):
            await s.summarize(chunks)

        assert max_observed <= max_concurrent
