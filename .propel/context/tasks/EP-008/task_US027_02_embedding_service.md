# TASK-US027-02 — `EmbeddingService`: Batch Embedding via LiteLLM with fastembed Fallback

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US027-02 |
| User Story | US-027 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `EmbeddingService`, which accepts a list of `ChunkPayload` objects and returns a list of `IndexedChunk` with populated `vector` fields. Satisfies AC-2 (configurable embedding model, default `text-embedding-3-small`) and AC-6 (throughput ≥ 1,000 chunks/min via batching and `asyncio.gather`).

## Implementation Details

**Technology:** Python 3.11+, LiteLLM `>=1.30`, fastembed `>=0.3`, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/indexing/embedding/service.py` — `EmbeddingService`, `EmbeddingSettings`
- `src/indexing/embedding/fastembed_provider.py` — `FastEmbedProvider` (local fallback)
- `tests/indexing/test_embedding_service.py`

**`EmbeddingSettings`:**

```python
# src/indexing/embedding/service.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", env_file=".env")

    model_id:             str   = "text-embedding-3-small"
    # Number of chunks per API call. OpenAI allows up to 2048 inputs per request.
    batch_size:           int   = 256
    # Number of concurrent batch requests. Tuned for ≥1 000 chunks/min at p50 latency.
    concurrency:          int   = 4
    # Timeout per batch call in seconds.
    timeout_s:            float = 30.0
    # If True, use fastembed (local BAAI/bge-small-en-v1.5) instead of LiteLLM.
    use_local_model:      bool  = False
    local_model_name:     str   = "BAAI/bge-small-en-v1.5"
```

**`EmbeddingService`:**

```python
# src/indexing/embedding/service.py (continued)
import asyncio
import litellm
from src.indexing.schemas.chunk import ChunkPayload, IndexedChunk
from src.indexing.embedding.fastembed_provider import FastEmbedProvider

class EmbeddingService:
    def __init__(self, settings: EmbeddingSettings | None = None) -> None:
        self._settings = settings or EmbeddingSettings()
        self._local: FastEmbedProvider | None = None
        if self._settings.use_local_model:
            self._local = FastEmbedProvider(self._settings.local_model_name)

    async def embed_batch(self, chunks: list[ChunkPayload]) -> list[IndexedChunk]:
        """
        Embed all chunks and return IndexedChunk list preserving input order.
        Splits chunks into sub-batches of `batch_size`, calls up to `concurrency`
        batches concurrently, then flattens results.
        """
        batches = _split(chunks, self._settings.batch_size)
        sem = asyncio.Semaphore(self._settings.concurrency)

        async def call_one(batch: list[ChunkPayload]) -> list[IndexedChunk]:
            async with sem:
                return await self._embed_one_batch(batch)

        results = await asyncio.gather(*[call_one(b) for b in batches])
        return [item for sublist in results for item in sublist]

    async def _embed_one_batch(self, batch: list[ChunkPayload]) -> list[IndexedChunk]:
        texts    = [c.text for c in batch]
        model_id = self._settings.model_id

        if self._local is not None:
            vectors = await asyncio.to_thread(self._local.embed, texts)
        else:
            response = await litellm.aembedding(
                model   = model_id,
                input   = texts,
                timeout = self._settings.timeout_s,
            )
            vectors = [item["embedding"] for item in response.data]

        return [
            IndexedChunk(payload=chunk, vector=vector, model_id=model_id)
            for chunk, vector in zip(batch, vectors, strict=True)
        ]


def _split(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]
```

**`FastEmbedProvider` (local model, runs in thread):**

```python
# src/indexing/embedding/fastembed_provider.py
from __future__ import annotations

_INSTANCE: FastEmbedProvider | None = None

class FastEmbedProvider:
    """
    Thin wrapper around fastembed.TextEmbedding.
    Instantiated once (singleton-per-model-name) to avoid repeated model loading.
    All public methods are synchronous — call via asyncio.to_thread().
    """
    _registry: dict[str, "FastEmbedProvider"] = {}

    def __new__(cls, model_name: str) -> "FastEmbedProvider":  # noqa: PYI034
        if model_name not in cls._registry:
            instance = super().__new__(cls)
            instance._model_name = model_name
            instance._model      = None   # lazy-initialised on first call
            cls._registry[model_name] = instance
        return cls._registry[model_name]

    def _ensure_loaded(self) -> None:
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self._model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        return [v.tolist() for v in self._model.embed(texts)]
```

**Throughput design (AC-6):**

Target: ≥ 1,000 chunks/min = ~17 chunks/s. At `batch_size=256` and `concurrency=4`, each batch call to `text-embedding-3-small` returns in ~1.5 s at p50 (OpenAI SLA), giving `4 × 256 / 1.5 ≈ 682 chunks/s` — comfortably above threshold. `EmbeddingSettings` values are tunable via env vars without code changes.

For fastembed (local), `BAAI/bge-small-en-v1.5` runs at ~5,000 chunks/min on CPU using batched numpy inference; throughput is not a concern on that path.

**Error handling:**

- `litellm.BadRequestError` (invalid input) → re-raise immediately; do not retry at this layer (caller's `SyncJobExecutor` handles retries at the job level)
- `litellm.RateLimitError` / `litellm.Timeout` → re-raise; the executor's exponential backoff covers these

## Acceptance Criteria

- [ ] `EmbeddingService.embed_batch([...256 chunks...])` issues exactly one LiteLLM call (one batch)
- [ ] `EmbeddingService.embed_batch([...512 chunks...])` issues exactly two concurrent LiteLLM calls
- [ ] `use_local_model=True` routes to `FastEmbedProvider.embed()` via `asyncio.to_thread`, never calling `litellm.aembedding()`
- [ ] Input order is preserved: `results[i].payload == chunks[i]` for all `i`
- [ ] `FastEmbedProvider("BAAI/bge-small-en-v1.5")` constructed twice returns the same instance (singleton)
- [ ] `mypy --strict` passes

## Dependencies

- TASK-US027-01 (`ChunkPayload`, `IndexedChunk` schemas)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `litellm.aembedding` via `AsyncMock`; no live API calls in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
