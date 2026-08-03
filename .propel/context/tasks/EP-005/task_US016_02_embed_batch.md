# TASK-US016-02 — Extend `QueryEmbedder` with `embed_batch()` for Chunk Arrays

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US016-02 |
| User Story | US-016 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / AI |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Extend the existing `QueryEmbedder` singleton (TASK-US012-02) with an `embed_batch()` method that accepts a list of text strings and returns a 2-D NumPy array of shape `(n, embedding_dim)`. Batch inference via `fastembed` is significantly faster than calling `embed()` in a loop and is required to keep semantic deduplication within the 300 ms budget for 50 chunks.

## Implementation Details

**Technology:** Python 3.11+, `fastembed>=0.3`, `numpy>=1.26`

**File locations:**
- `src/retrieval/embedding/embedder.py` — `QueryEmbedder.embed_batch()` added (extends TASK-US012-02)
- `tests/retrieval/embedding/test_embedder_batch.py`

**Extended `QueryEmbedder`:**

```python
# src/retrieval/embedding/embedder.py  (extend — do NOT redefine existing embed() or singleton logic)
import numpy as np

class QueryEmbedder:
    # ... existing __init__, get(), embed() unchanged ...

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
        embeddings = list(self._model.embed(texts))    # fastembed accepts list[str]
        return np.array(embeddings, dtype=np.float32)  # shape: (n, 384)

    @property
    def embedding_dim(self) -> int:
        """Return the dimensionality of the embedding model output."""
        return 384   # bge-small-en-v1.5 output dimension
```

**fastembed batch behaviour:**
`TextEmbedding.embed(texts: list[str])` already processes inputs in batches internally. Passing all 50 texts at once lets fastembed optimise padding and GPU/CPU parallelism, typically producing results in 80–200 ms on CPU for 50 short code chunks.

**NumPy dtype choice:**
`float32` halves memory usage versus `float64` (50 × 384 × 4 bytes = 76.8 KB vs 153.6 KB). Cosine similarity via matrix multiplication gives identical ranking results at `float32` precision.

**Single-text fast path preserved:**
The existing `embed(text: str) -> list[float]` method is unchanged and continues to serve query embedding in the retrieval path (TASK-US012-02, TASK-US013-03). `embed_batch` is exclusively used by the semantic deduplication path — the two methods are not merged.

**Benchmark (informative, not CI-gated here):**
50 chunks × ~50 tokens each on a 4-core CPU: `embed_batch` completes in ≈ 80–150 ms. The CI benchmark gate lives in TASK-US016-04 (end-to-end 300 ms).

## Acceptance Criteria

- [ ] `embed_batch(["hello", "world"])` returns an `ndarray` of shape `(2, 384)` and dtype `float32`
- [ ] Row order of the output matches the input list order
- [ ] `embed_batch([])` raises `ValueError`
- [ ] `embed_batch(texts)` does NOT call `embed()` internally — it calls `self._model.embed(texts)` directly to avoid per-text overhead
- [ ] The `QueryEmbedder` singleton is not re-instantiated by `embed_batch` — it uses the existing `_model`
- [ ] `embedding_dim` property returns `384`

## Dependencies

- TASK-US012-02 (`QueryEmbedder` singleton — extended here; existing `embed()` method unchanged)
- TASK-US016-03 (`compute_similarity_matrix()` — consumes the `ndarray` output)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All existing `QueryEmbedder` unit tests continue to pass
- [ ] New unit tests cover: shape, dtype, row-order, empty-input error, singleton reuse
- [ ] `fastembed` is called with the full list — no per-text loop in `embed_batch`
- [ ] `mypy --strict` passes; no `ruff` lint errors
