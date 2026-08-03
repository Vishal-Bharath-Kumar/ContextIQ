"""EmbeddingService and EmbeddingSettings — TASK-US027-02.

EmbeddingService accepts a list of ChunkPayload objects and returns a
list of IndexedChunk with populated ``vector`` fields.  It satisfies:

  AC-2  Configurable embedding model (default ``text-embedding-3-small``).
  AC-6  Throughput ≥ 1 000 chunks/min via batching + asyncio.gather.
"""
from __future__ import annotations

import asyncio

import litellm
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.indexing.embedding.fastembed_provider import FastEmbedProvider
from src.indexing.schemas.chunk import ChunkPayload, IndexedChunk


class EmbeddingSettings(BaseSettings):
    """Runtime-configurable embedding parameters.

    All fields are overridable via ``EMBEDDING_*`` environment variables
    or a ``.env`` file at the project root.
    """

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", env_file=".env")

    model_id: str = "text-embedding-3-small"
    # Number of chunks per API call.  OpenAI allows up to 2 048 inputs.
    batch_size: int = 256
    # Maximum number of concurrent batch requests.
    concurrency: int = 4
    # Per-batch call timeout in seconds.
    timeout_s: float = 30.0
    # Route to fastembed (local BAAI/bge-small-en-v1.5) instead of LiteLLM.
    use_local_model: bool = False
    local_model_name: str = "BAAI/bge-small-en-v1.5"


class EmbeddingService:
    """Batch embedding service backed by LiteLLM or local fastembed."""

    def __init__(self, settings: EmbeddingSettings | None = None) -> None:
        self._settings = settings or EmbeddingSettings()
        self._local: FastEmbedProvider | None = None
        if self._settings.use_local_model:
            self._local = FastEmbedProvider(self._settings.local_model_name)

    async def embed_batch(self, chunks: list[ChunkPayload]) -> list[IndexedChunk]:
        """Embed *chunks* and return an ``IndexedChunk`` list in input order.

        Splits *chunks* into sub-batches of ``batch_size``, dispatches up to
        ``concurrency`` batches concurrently, then flattens the results while
        preserving insertion order.
        """
        if not chunks:
            return []

        batches = _split(chunks, self._settings.batch_size)
        sem = asyncio.Semaphore(self._settings.concurrency)

        async def call_one(batch: list[ChunkPayload]) -> list[IndexedChunk]:
            async with sem:
                return await self._embed_one_batch(batch)

        results = await asyncio.gather(*[call_one(b) for b in batches])
        return [item for sublist in results for item in sublist]

    async def _embed_one_batch(self, batch: list[ChunkPayload]) -> list[IndexedChunk]:
        texts = [c.text for c in batch]
        model_id = self._settings.model_id

        if self._local is not None:
            vectors: list[list[float]] = await asyncio.to_thread(
                self._local.embed, texts
            )
        else:
            response = await litellm.aembedding(
                model=model_id,
                input=texts,
                timeout=self._settings.timeout_s,
            )
            vectors = [item["embedding"] for item in response.data]

        return [
            IndexedChunk(payload=chunk, vector=vector, model_id=model_id)
            for chunk, vector in zip(batch, vectors, strict=True)
        ]


def _split(items: list[ChunkPayload], size: int) -> list[list[ChunkPayload]]:
    """Partition *items* into consecutive sub-lists of at most *size* elements."""
    return [items[i : i + size] for i in range(0, len(items), size)]
