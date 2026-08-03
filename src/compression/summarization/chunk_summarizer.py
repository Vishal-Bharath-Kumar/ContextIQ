"""LLM-based parallel chunk summariser (TASK-US017-04 / EP-005)."""

from __future__ import annotations

import asyncio

from src.compression.summarization.chain import SummarizationChain
from src.compression.summarization.settings import get_summarization_settings
from src.retrieval.ranking.filters import count_tokens
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


class ChunkSummarizer:
    """Summarise over-threshold chunks in parallel, bounded by a semaphore.

    Chunks whose token count is at or below ``token_threshold`` are returned
    unchanged.  Chunks that exceed the threshold are summarised concurrently,
    with at most ``max_concurrent`` LLM calls in-flight at any moment.

    Fail-open policy: if the LLM call for an individual chunk raises any
    exception the original chunk is returned and ``compressed`` stays ``False``.
    The pipeline as a whole never fails due to a single summarisation error.
    """

    def __init__(
        self,
        chain: SummarizationChain | None = None,
        callbacks: list | None = None,
    ) -> None:
        self._chain = chain or SummarizationChain()
        self._settings = get_summarization_settings()
        self._callbacks = callbacks or []

    async def summarize(
        self,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Summarise all chunks exceeding the token threshold.

        Sub-threshold chunks are passed through unchanged.
        On LLM failure for a specific chunk, the original is retained (fail-open).

        Args:
            chunks: Ranked retrieval results to compress.

        Returns:
            A list of chunks in the same order as the input, with over-threshold
            chunks replaced by their LLM-generated summaries.
        """
        if not chunks:
            return []

        threshold = self._settings.token_threshold
        semaphore = asyncio.Semaphore(self._settings.max_concurrent)

        async def _maybe_summarise(chunk: RetrievedChunk) -> RetrievedChunk:
            token_count = count_tokens(chunk.content)
            if token_count <= threshold:
                return chunk
            async with semaphore:
                try:
                    output = await self._chain.summarise(
                        content=chunk.content,
                        input_tokens=token_count,
                        callbacks=self._callbacks,
                    )
                    return chunk.model_copy(update={
                        "content": output.summary,
                        "compressed": True,
                        "original_token_count": token_count,
                    })
                except Exception:  # noqa: BLE001
                    # Fail-open: return original chunk on any LLM error
                    return chunk

        return list(await asyncio.gather(*[_maybe_summarise(c) for c in chunks]))
