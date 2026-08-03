"""Unit tests for QueryEmbedder.embed_batch() and embedding_dim — TASK-US016-02.

All tests run without a live fastembed model:
  - fastembed is stubbed via sys.modules injection.
  - QueryEmbedder._model is replaced with a MagicMock that returns controlled
    numpy arrays so shape, dtype, and row-order can be verified deterministically.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Stub fastembed before any src.retrieval.* import
# ---------------------------------------------------------------------------
if "fastembed" not in sys.modules:
    _fake_fastembed = types.ModuleType("fastembed")
    _fake_fastembed.TextEmbedding = MagicMock  # type: ignore[attr-defined]
    sys.modules["fastembed"] = _fake_fastembed

from src.retrieval.embedding.embedder import QueryEmbedder  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 384
_ROW_A = [float(i) for i in range(EMBEDDING_DIM)]       # distinct row 0
_ROW_B = [float(i + 1) for i in range(EMBEDDING_DIM)]   # distinct row 1


def _embedder_with_mock_model(rows: list[list[float]]) -> QueryEmbedder:
    """Return a QueryEmbedder whose _model.embed() yields the given rows."""
    embedder = QueryEmbedder.__new__(QueryEmbedder)
    mock_model = MagicMock()
    mock_model.embed.return_value = iter([np.array(r, dtype=np.float32) for r in rows])
    embedder._model = mock_model
    return embedder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmbedBatchShape:
    def test_returns_2d_ndarray(self) -> None:
        embedder = _embedder_with_mock_model([_ROW_A, _ROW_B])
        result = embedder.embed_batch(["hello", "world"])
        assert isinstance(result, np.ndarray)
        assert result.ndim == 2

    def test_shape_matches_input_length(self) -> None:
        embedder = _embedder_with_mock_model([_ROW_A, _ROW_B])
        result = embedder.embed_batch(["hello", "world"])
        assert result.shape == (2, EMBEDDING_DIM)

    def test_single_text_shape(self) -> None:
        embedder = _embedder_with_mock_model([_ROW_A])
        result = embedder.embed_batch(["single"])
        assert result.shape == (1, EMBEDDING_DIM)


class TestEmbedBatchDtype:
    def test_dtype_is_float32(self) -> None:
        embedder = _embedder_with_mock_model([_ROW_A, _ROW_B])
        result = embedder.embed_batch(["a", "b"])
        assert result.dtype == np.float32


class TestEmbedBatchRowOrder:
    def test_row_order_matches_input_order(self) -> None:
        embedder = _embedder_with_mock_model([_ROW_A, _ROW_B])
        result = embedder.embed_batch(["first", "second"])
        np.testing.assert_array_almost_equal(result[0], np.array(_ROW_A, dtype=np.float32))
        np.testing.assert_array_almost_equal(result[1], np.array(_ROW_B, dtype=np.float32))


class TestEmbedBatchEmptyInput:
    def test_empty_list_raises_value_error(self) -> None:
        embedder = _embedder_with_mock_model([])
        with pytest.raises(ValueError, match="embed_batch requires at least one text string"):
            embedder.embed_batch([])


class TestEmbedBatchCallsModelDirectly:
    def test_calls_model_embed_with_full_list_not_per_text(self) -> None:
        """embed_batch must call self._model.embed(texts) once, not in a loop."""
        embedder = _embedder_with_mock_model([_ROW_A, _ROW_B])
        texts = ["chunk one", "chunk two"]
        embedder.embed_batch(texts)
        embedder._model.embed.assert_called_once_with(texts)

    def test_does_not_call_embed_method(self) -> None:
        """embed_batch must not delegate to the public embed() method."""
        embedder = _embedder_with_mock_model([_ROW_A])
        with patch.object(embedder, "embed") as mock_embed:
            embedder.embed_batch(["one text"])
            mock_embed.assert_not_called()


class TestEmbedBatchSingletonReuse:
    def setup_method(self) -> None:
        QueryEmbedder._instance = None

    def teardown_method(self) -> None:
        QueryEmbedder._instance = None

    def test_embed_batch_uses_existing_model(self) -> None:
        """embed_batch must not trigger a new model instantiation."""
        embedder = _embedder_with_mock_model([_ROW_A])
        QueryEmbedder._instance = embedder
        instance_before = QueryEmbedder._instance
        embedder.embed_batch(["check singleton"])
        assert QueryEmbedder._instance is instance_before


class TestEmbeddingDimProperty:
    def test_embedding_dim_returns_384(self) -> None:
        embedder = _embedder_with_mock_model([])
        assert embedder.embedding_dim == 384
