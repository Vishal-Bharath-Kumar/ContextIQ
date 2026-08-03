"""Unit tests for EmbeddingService and FastEmbedProvider — TASK-US027-02.

All tests run without live API or model calls:
  - litellm.aembedding is mocked via AsyncMock.
  - FastEmbedProvider.embed is mocked via MagicMock / AsyncMock.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.indexing.embedding.fastembed_provider import FastEmbedProvider
from src.indexing.embedding.service import EmbeddingService, EmbeddingSettings
from src.indexing.schemas.chunk import ChunkPayload, IndexedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOURCE_ID = uuid4()


def _make_chunk(text: str = "hello world") -> ChunkPayload:
    return ChunkPayload(
        source_id=SOURCE_ID,
        tenant_id="acme",
        document_id="doc:1",
        text=text,
        token_count=2,
    )


def _fake_response(n: int) -> MagicMock:
    """Build a fake litellm EmbeddingResponse with *n* vectors of dim=4."""
    resp = MagicMock()
    resp.data = [{"embedding": [0.1, 0.2, 0.3, 0.4]} for _ in range(n)]
    return resp


# ---------------------------------------------------------------------------
# EmbeddingService — LiteLLM path
# ---------------------------------------------------------------------------


class TestEmbeddingServiceLiteLLM:
    """Tests for the default (LiteLLM) embedding path."""

    def _settings(self, **overrides: object) -> EmbeddingSettings:
        base: dict[str, object] = {
            "model_id": "text-embedding-3-small",
            "batch_size": 256,
            "concurrency": 4,
            "timeout_s": 30.0,
            "use_local_model": False,
        }
        base.update(overrides)
        return EmbeddingSettings.model_construct(**base)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_single_batch_256_chunks_one_call(self) -> None:
        """256 chunks with batch_size=256 → exactly 1 litellm.aembedding call."""
        chunks = [_make_chunk(f"text {i}") for i in range(256)]

        with patch("src.indexing.embedding.service.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(return_value=_fake_response(256))
            svc = EmbeddingService(self._settings())
            results = await svc.embed_batch(chunks)

        mock_litellm.aembedding.assert_called_once()
        assert len(results) == 256

    @pytest.mark.asyncio
    async def test_512_chunks_two_concurrent_calls(self) -> None:
        """512 chunks with batch_size=256 → exactly 2 litellm.aembedding calls."""
        chunks = [_make_chunk(f"text {i}") for i in range(512)]

        with patch("src.indexing.embedding.service.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(return_value=_fake_response(256))
            svc = EmbeddingService(self._settings())
            results = await svc.embed_batch(chunks)

        assert mock_litellm.aembedding.call_count == 2
        assert len(results) == 512

    @pytest.mark.asyncio
    async def test_order_preserved(self) -> None:
        """results[i].payload == chunks[i] for all i."""
        chunks = [_make_chunk(f"text {i}") for i in range(10)]

        with patch("src.indexing.embedding.service.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(return_value=_fake_response(10))
            svc = EmbeddingService(self._settings(batch_size=10))
            results = await svc.embed_batch(chunks)

        for i, result in enumerate(results):
            assert result.payload == chunks[i]

    @pytest.mark.asyncio
    async def test_returns_indexed_chunks(self) -> None:
        """All returned items are IndexedChunk instances."""
        chunks = [_make_chunk()]

        with patch("src.indexing.embedding.service.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(return_value=_fake_response(1))
            svc = EmbeddingService(self._settings(batch_size=1))
            results = await svc.embed_batch(chunks)

        assert len(results) == 1
        assert isinstance(results[0], IndexedChunk)
        assert results[0].model_id == "text-embedding-3-small"
        assert results[0].vector == [0.1, 0.2, 0.3, 0.4]

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_list(self) -> None:
        """embed_batch([]) returns [] without calling litellm."""
        with patch("src.indexing.embedding.service.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock()
            svc = EmbeddingService(self._settings())
            results = await svc.embed_batch([])

        mock_litellm.aembedding.assert_not_called()
        assert results == []

    @pytest.mark.asyncio
    async def test_litellm_bad_request_propagates(self) -> None:
        """litellm.BadRequestError is re-raised without retry."""
        chunks = [_make_chunk()]

        with patch("src.indexing.embedding.service.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(
                side_effect=Exception("BadRequest: invalid input")
            )
            svc = EmbeddingService(self._settings(batch_size=1))
            with pytest.raises(Exception, match="BadRequest"):
                await svc.embed_batch(chunks)


# ---------------------------------------------------------------------------
# EmbeddingService — local fastembed path
# ---------------------------------------------------------------------------


class TestEmbeddingServiceLocal:
    """Tests for the use_local_model=True (fastembed) path."""

    def _settings(self, **overrides: object) -> EmbeddingSettings:
        base: dict[str, object] = {
            "model_id": "BAAI/bge-small-en-v1.5",
            "batch_size": 256,
            "concurrency": 4,
            "timeout_s": 30.0,
            "use_local_model": True,
            "local_model_name": "BAAI/bge-small-en-v1.5",
        }
        base.update(overrides)
        return EmbeddingSettings.model_construct(**base)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_local_path_never_calls_litellm(self) -> None:
        """use_local_model=True never invokes litellm.aembedding."""
        chunks = [_make_chunk(f"t{i}") for i in range(5)]
        fake_vectors = [[float(i)] * 4 for i in range(5)]

        with patch(
            "src.indexing.embedding.service.litellm"
        ) as mock_litellm, patch.object(
            FastEmbedProvider, "embed", return_value=fake_vectors
        ):
            mock_litellm.aembedding = AsyncMock()
            # Reset singleton registry so constructor creates fresh instance
            FastEmbedProvider._registry.clear()
            svc = EmbeddingService(self._settings(batch_size=5))
            results = await svc.embed_batch(chunks)

        mock_litellm.aembedding.assert_not_called()
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_local_path_order_preserved(self) -> None:
        """Input order is preserved when using the local fastembed path."""
        chunks = [_make_chunk(f"text {i}") for i in range(4)]
        fake_vectors = [[float(i)] * 4 for i in range(4)]

        FastEmbedProvider._registry.clear()
        with patch.object(FastEmbedProvider, "embed", return_value=fake_vectors):
            svc = EmbeddingService(self._settings(batch_size=4))
            results = await svc.embed_batch(chunks)

        for i, result in enumerate(results):
            assert result.payload == chunks[i]
            assert result.vector == fake_vectors[i]


# ---------------------------------------------------------------------------
# FastEmbedProvider — singleton behaviour
# ---------------------------------------------------------------------------


class TestFastEmbedProviderSingleton:
    def setup_method(self) -> None:
        # Isolate registry between tests
        FastEmbedProvider._registry.clear()

    def test_same_model_name_returns_same_instance(self) -> None:
        """Constructing FastEmbedProvider twice with same name yields one object."""
        a = FastEmbedProvider("BAAI/bge-small-en-v1.5")
        b = FastEmbedProvider("BAAI/bge-small-en-v1.5")
        assert a is b

    def test_different_model_names_return_different_instances(self) -> None:
        """Two different model names yield two distinct instances."""
        a = FastEmbedProvider("BAAI/bge-small-en-v1.5")
        b = FastEmbedProvider("BAAI/bge-base-en-v1.5")
        assert a is not b

    def test_embed_delegates_to_model(self) -> None:
        """embed() calls _model.embed and converts array-like values to lists."""
        provider = FastEmbedProvider("BAAI/bge-small-en-v1.5")

        # Use a MagicMock with a .tolist() method to avoid a numpy dependency.
        fake_vec = MagicMock()
        fake_vec.tolist.return_value = [0.1, 0.2, 0.3]
        mock_model = MagicMock()
        mock_model.embed.return_value = [fake_vec]
        provider._model = mock_model  # inject mock; bypass _ensure_loaded

        result = provider.embed(["hello"])
        mock_model.embed.assert_called_once_with(["hello"])
        assert result == [[0.1, 0.2, 0.3]]
        assert isinstance(result[0], list)
