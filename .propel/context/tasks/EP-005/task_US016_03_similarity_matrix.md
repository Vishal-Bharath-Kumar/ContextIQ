# TASK-US016-03 — Cosine Similarity Matrix and Near-Duplicate Pair Detection

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US016-03 |
| User Story | US-016 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement two pure functions: `compute_similarity_matrix()` computes the pairwise cosine similarity between all chunk embeddings using normalised matrix multiplication, and `find_near_duplicate_pairs()` extracts the upper-triangle indices where similarity meets or exceeds the configured threshold. These are the computational core of semantic deduplication, operating entirely on NumPy arrays with no I/O.

## Implementation Details

**Technology:** Python 3.11+, `numpy>=1.26`

**File locations:**
- `src/compression/semantic/similarity.py` — `compute_similarity_matrix()`, `find_near_duplicate_pairs()`
- `tests/compression/semantic/test_similarity.py`

**`compute_similarity_matrix()`:**

Cosine similarity between normalised vectors reduces to a dot product. For a matrix $E$ of shape $(n, d)$ where each row is $\ell_2$-normalised:

$$S = E_{\text{norm}} \cdot E_{\text{norm}}^T \quad \in \mathbb{R}^{n \times n}$$

```python
# src/compression/semantic/similarity.py
import numpy as np

def compute_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Compute the pairwise cosine similarity matrix.

    Args:
        embeddings: float32 array of shape (n, d) — raw (not normalised) embeddings.

    Returns:
        float32 array of shape (n, n), values in [-1.0, 1.0].
        Diagonal is always 1.0 (self-similarity).
    """
    if embeddings.ndim != 2 or embeddings.shape[0] == 0:
        raise ValueError(f"Expected 2-D non-empty array, got shape {embeddings.shape}")

    # L2-normalise each row; add epsilon to avoid division by zero for zero vectors
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    normed = embeddings / norms                       # shape: (n, d)
    return (normed @ normed.T).astype(np.float32)     # shape: (n, n)
```

**`find_near_duplicate_pairs()`:**

```python
def find_near_duplicate_pairs(
    similarity_matrix: np.ndarray,
    threshold:         float,
) -> list[tuple[int, int]]:
    """Return (i, j) index pairs where similarity ≥ threshold and i < j.

    Upper-triangle only — avoids returning both (i,j) and (j,i) for the
    same pair, and excludes the self-similarity diagonal.
    """
    n = similarity_matrix.shape[0]
    # Extract upper triangle (k=1 excludes diagonal)
    rows, cols = np.where(
        np.triu(similarity_matrix, k=1) >= threshold
    )
    return list(zip(rows.tolist(), cols.tolist()))
```

**Performance analysis for n=50:**
- `compute_similarity_matrix`: 50 × 50 dot product after normalisation ≈ < 1 ms on CPU (numpy BLAS)
- `find_near_duplicate_pairs`: upper-triangle extraction on a 50×50 matrix ≈ < 0.1 ms
- Total similarity step contributes < 2 ms to the 300 ms budget; the dominant cost is `embed_batch` (TASK-US016-02)

**Numerical stability:**
- L2-normalisation with an epsilon guard prevents `NaN` propagation for zero-norm embeddings (e.g. empty-content chunks)
- Output is cast to `float32` to match input dtype and prevent silent precision upgrades to `float64`

## Acceptance Criteria

- [ ] `compute_similarity_matrix(E)` diagonal values are all `1.0` (self-similarity)
- [ ] `compute_similarity_matrix(E)` is symmetric: `S[i, j] == S[j, i]`
- [ ] For two identical vectors, `compute_similarity_matrix` returns `1.0` at both off-diagonal positions
- [ ] For two orthogonal vectors (zero dot product), similarity is `0.0`
- [ ] `compute_similarity_matrix` with a single row `(1, d)` returns a `(1, 1)` array with value `1.0`
- [ ] `find_near_duplicate_pairs` returns only pairs where `i < j` — no symmetric duplicates
- [ ] `find_near_duplicate_pairs` with `threshold=1.01` returns `[]` (no pair can exceed 1.0)
- [ ] `compute_similarity_matrix` raises `ValueError` for empty or 1-D input

## Dependencies

- TASK-US016-02 (`embed_batch()` — produces the `ndarray` input)
- TASK-US016-04 (`SemanticDeduplicator` — consumes both functions)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 90% for `src/compression/semantic/similarity.py`
- [ ] Tests cover: identical vectors, orthogonal vectors, threshold boundary, single-row matrix, zero-norm vector guard
- [ ] No Python loops over matrix elements — all operations use NumPy vectorised functions
- [ ] `mypy --strict` passes; no `ruff` lint errors
