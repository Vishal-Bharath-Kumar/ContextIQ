"""Query embedding singleton — model is loaded once at process start."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from fastembed import TextEmbedding as _TextEmbedding


class QueryEmbedder:
    """Singleton embedding wrapper — model is loaded once at process start."""

    _instance: QueryEmbedder | None = None

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding  # lazy import — only loaded at first instantiation

        self._model: _TextEmbedding = TextEmbedding(model_name=model_name)

    @classmethod
    def get(cls) -> QueryEmbedder:
        if cls._instance is None:
            cls._instance = QueryEmbedder()
        return cls._instance

    def embed(self, text: str) -> list[float]:
        return list(self._model.embed([text]))[0].tolist()

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed a list of texts in a single fastembed batch call.

        Returns:
            ndarray of shape (len(texts), embedding_dim), dtype float32.
            Row order matches input order.

        Raises:
            ValueError: if `texts` is empty.
        """
        if not texts:
            raise ValueError("embed_batch requires at least one text string")
        import numpy as np  # noqa: PLC0415 — lazy import mirrors fastembed pattern

        embeddings = list(self._model.embed(texts))
        return np.array(embeddings, dtype=np.float32)

    @property
    def embedding_dim(self) -> int:
        """Return the dimensionality of the embedding model output."""
        return 384
