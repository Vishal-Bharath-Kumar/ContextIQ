"""Unit tests for src/compression/semantic/similarity.py."""

from __future__ import annotations

import numpy as np
import pytest

from src.compression.semantic.similarity import compute_similarity_matrix, find_near_duplicate_pairs

# ---------------------------------------------------------------------------
# compute_similarity_matrix — structural / correctness tests
# ---------------------------------------------------------------------------


class TestComputeSimilarityMatrix:
    def test_diagonal_is_one(self) -> None:
        """Self-similarity must be 1.0 for all rows."""
        rng = np.random.default_rng(0)
        embeddings = rng.standard_normal((5, 8)).astype(np.float32)
        S = compute_similarity_matrix(embeddings)
        np.testing.assert_allclose(np.diag(S), 1.0, atol=1e-6)

    def test_symmetry(self) -> None:
        """S[i, j] == S[j, i] for all i, j."""
        rng = np.random.default_rng(1)
        embeddings = rng.standard_normal((6, 16)).astype(np.float32)
        S = compute_similarity_matrix(embeddings)
        np.testing.assert_allclose(S, S.T, atol=1e-6)

    def test_identical_vectors_similarity_one(self) -> None:
        """Two identical rows produce similarity 1.0 at both off-diagonal positions."""
        v = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32)
        S = compute_similarity_matrix(v)
        assert S[0, 1] == pytest.approx(1.0, abs=1e-6)
        assert S[1, 0] == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors_similarity_zero(self) -> None:
        """Two orthogonal vectors produce similarity 0.0."""
        v = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        S = compute_similarity_matrix(v)
        assert S[0, 1] == pytest.approx(0.0, abs=1e-6)
        assert S[1, 0] == pytest.approx(0.0, abs=1e-6)

    def test_single_row_returns_1x1_matrix(self) -> None:
        """A (1, d) input must return a (1, 1) array with value 1.0."""
        v = np.array([[3.0, 4.0]], dtype=np.float32)
        S = compute_similarity_matrix(v)
        assert S.shape == (1, 1)
        assert S[0, 0] == pytest.approx(1.0, abs=1e-6)

    def test_output_dtype_is_float32(self) -> None:
        """Output array must be float32 regardless of input precision."""
        embeddings = np.ones((3, 4), dtype=np.float64)
        S = compute_similarity_matrix(embeddings)
        assert S.dtype == np.float32

    def test_output_shape(self) -> None:
        """Output shape is (n, n) for input (n, d)."""
        embeddings = np.ones((7, 12), dtype=np.float32)
        S = compute_similarity_matrix(embeddings)
        assert S.shape == (7, 7)

    def test_values_bounded(self) -> None:
        """All similarity values must lie in [-1.0, 1.0]."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((10, 32)).astype(np.float32)
        S = compute_similarity_matrix(embeddings)
        assert float(S.min()) >= -1.0 - 1e-5
        assert float(S.max()) <= 1.0 + 1e-5

    def test_zero_norm_vector_guard(self) -> None:
        """Zero-norm vector must not produce NaN; no NaN propagation."""
        v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32)
        S = compute_similarity_matrix(v)
        assert not np.any(np.isnan(S)), "NaN values detected with zero-norm vector"
        # Zero-norm vector similarity is 0.0 (epsilon guard prevents NaN, not value correction)
        assert not np.any(np.isnan(S))

    def test_antiparallel_vectors(self) -> None:
        """Opposite-direction vectors produce similarity -1.0."""
        v = np.array([[1.0, 0.0], [-1.0, 0.0]], dtype=np.float32)
        S = compute_similarity_matrix(v)
        assert S[0, 1] == pytest.approx(-1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# compute_similarity_matrix — invalid input tests
# ---------------------------------------------------------------------------


class TestComputeSimilarityMatrixInvalidInput:
    def test_raises_for_1d_input(self) -> None:
        with pytest.raises(ValueError, match="Expected 2-D non-empty array"):
            compute_similarity_matrix(np.array([1.0, 2.0, 3.0], dtype=np.float32))

    def test_raises_for_empty_2d_input(self) -> None:
        with pytest.raises(ValueError, match="Expected 2-D non-empty array"):
            compute_similarity_matrix(np.empty((0, 5), dtype=np.float32))

    def test_raises_for_3d_input(self) -> None:
        with pytest.raises(ValueError, match="Expected 2-D non-empty array"):
            compute_similarity_matrix(np.ones((2, 3, 4), dtype=np.float32))


# ---------------------------------------------------------------------------
# find_near_duplicate_pairs
# ---------------------------------------------------------------------------


class TestFindNearDuplicatePairs:
    def _identical_pair_matrix(self) -> np.ndarray:
        """2×2 similarity matrix where off-diagonal is 1.0."""
        return np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float32)

    def test_returns_only_upper_triangle_pairs(self) -> None:
        """Result contains only (i, j) with i < j — no symmetric duplicates."""
        S = self._identical_pair_matrix()
        pairs = find_near_duplicate_pairs(S, threshold=0.9)
        assert pairs == [(0, 1)]

    def test_threshold_boundary_exact_match(self) -> None:
        """Pair at exactly the threshold value is included."""
        S = np.array([[1.0, 0.92], [0.92, 1.0]], dtype=np.float32)
        pairs = find_near_duplicate_pairs(S, threshold=0.92)
        assert (0, 1) in pairs

    def test_threshold_just_above_excludes_pair(self) -> None:
        """Pair just below threshold is excluded."""
        S = np.array([[1.0, 0.919], [0.919, 1.0]], dtype=np.float32)
        pairs = find_near_duplicate_pairs(S, threshold=0.92)
        assert pairs == []

    def test_threshold_above_one_returns_empty(self) -> None:
        """threshold=1.01 — no cosine similarity can exceed 1.0."""
        rng = np.random.default_rng(7)
        embeddings = rng.standard_normal((5, 8)).astype(np.float32)
        S = compute_similarity_matrix(embeddings)
        pairs = find_near_duplicate_pairs(S, threshold=1.01)
        assert pairs == []

    def test_no_pairs_when_all_orthogonal(self) -> None:
        """Identity-like matrix with high threshold produces no pairs."""
        S = np.eye(4, dtype=np.float32)
        pairs = find_near_duplicate_pairs(S, threshold=0.5)
        assert pairs == []

    def test_all_pairs_when_low_threshold(self) -> None:
        """Low threshold returns all upper-triangle pairs for a fully positive matrix."""
        S = np.ones((3, 3), dtype=np.float32)
        # threshold=0.5 — all upper-triangle values (1.0) exceed it; lower-triangle
        # values zeroed by np.triu(k=1) do not (0.0 < 0.5), so only real pairs returned.
        pairs = find_near_duplicate_pairs(S, threshold=0.5)
        assert sorted(pairs) == [(0, 1), (0, 2), (1, 2)]

    def test_result_pairs_satisfy_i_less_than_j(self) -> None:
        """Every returned pair must have i < j."""
        rng = np.random.default_rng(99)
        embeddings = rng.standard_normal((8, 16)).astype(np.float32)
        S = compute_similarity_matrix(embeddings)
        pairs = find_near_duplicate_pairs(S, threshold=0.5)
        for i, j in pairs:
            assert i < j

    def test_return_type_is_list_of_tuples(self) -> None:
        """Return type must be list[tuple[int, int]]."""
        S = self._identical_pair_matrix()
        pairs = find_near_duplicate_pairs(S, threshold=0.9)
        assert isinstance(pairs, list)
        for item in pairs:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], int) and isinstance(item[1], int)

    def test_single_element_matrix_returns_empty(self) -> None:
        """1×1 matrix has no upper-triangle pairs."""
        S = np.array([[1.0]], dtype=np.float32)
        pairs = find_near_duplicate_pairs(S, threshold=0.9)
        assert pairs == []
