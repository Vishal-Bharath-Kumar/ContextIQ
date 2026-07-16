"""Local embedding provider using fastembed — TASK-US027-02.

FastEmbedProvider is a singleton-per-model-name wrapper around
``fastembed.TextEmbedding``.  All public methods are synchronous;
callers must invoke them via ``asyncio.to_thread()``.
"""
from __future__ import annotations


class FastEmbedProvider:
    """Thin wrapper around fastembed.TextEmbedding.

    Instantiated once per model name to avoid repeated model loading.
    All public methods are synchronous — call via asyncio.to_thread().
    """

    _registry: dict[str, FastEmbedProvider] = {}

    def __new__(cls, model_name: str) -> FastEmbedProvider:  # noqa: PYI034
        if model_name not in cls._registry:
            instance = super().__new__(cls)
            instance._model_name = model_name  # type: ignore[attr-defined]
            instance._model = None  # lazy-initialised on first call  # type: ignore[attr-defined]
            cls._registry[model_name] = instance
        return cls._registry[model_name]

    def _ensure_loaded(self) -> None:
        if self._model is None:
            from fastembed import TextEmbedding  # type: ignore[import-untyped]

            self._model = TextEmbedding(model_name=self._model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one float vector per input text."""
        self._ensure_loaded()
        return [v.tolist() for v in self._model.embed(texts)]
