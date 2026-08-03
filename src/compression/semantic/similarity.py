"""Cosine similarity matrix and near-duplicate pair detection for semantic deduplication."""

from __future__ import annotations

import numpy as np


def compute_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Compute the pairwise cosine similarity matrix.

    Args:
        embeddings: float32 array of shape (n, d) — raw (not normalised) embeddings.

    Returns:
        float32 array of shape (n, n), values in [-1.0, 1.0].
        Diagonal is always 1.0 (self-similarity).

    Raises:
        ValueError: If embeddings is not a 2-D non-empty array.
    """
    if embeddings.ndim != 2 or embeddings.shape[0] == 0:
        raise ValueError(f"Expected 2-D non-empty array, got shape {embeddings.shape}")

    # L2-normalise each row; epsilon guard prevents division by zero for zero-norm vectors
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    normed = embeddings / norms  # shape: (n, d)
    return (normed @ normed.T).astype(np.float32)  # shape: (n, n)


def find_near_duplicate_pairs(
    similarity_matrix: np.ndarray,
    threshold: float,
) -> list[tuple[int, int]]:
    """Return (i, j) index pairs where similarity >= threshold and i < j.

    Upper-triangle only — avoids returning both (i, j) and (j, i) for the
    same pair, and excludes the self-similarity diagonal.

    Args:
        similarity_matrix: float32 array of shape (n, n) from compute_similarity_matrix.
        threshold: minimum cosine similarity to qualify as a near-duplicate.

    Returns:
        List of (i, j) tuples with i < j where similarity_matrix[i, j] >= threshold.
    """
    rows, cols = np.where(np.triu(similarity_matrix, k=1) >= threshold)
    return list(zip(rows.tolist(), cols.tolist(), strict=False))
