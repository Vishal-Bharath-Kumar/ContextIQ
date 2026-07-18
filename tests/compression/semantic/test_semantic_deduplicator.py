"""Unit tests for SemanticDeduplicator and UnionFind (TASK-US016-04)."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from src.compression.schemas.removed_chunk import RemovalReason
from src.compression.semantic.semantic_deduplicator import SemanticDeduplicator, UnionFind
from tests.compression.semantic.fixtures import make_chunk, make_chunks

EMBED_DIM = 384


# ---------------------------------------------------------------------------
# UnionFind
# ---------------------------------------------------------------------------


class TestUnionFind:
    def test_initial_state_each_node_is_its_own_root(self) -> None:
        uf = UnionFind(5)
        for i in range(5):
            assert uf.find(i) == i

    def test_union_merges_two_nodes(self) -> None:
        uf = UnionFind(4)
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)

    def test_find_is_idempotent(self) -> None:
        uf = UnionFind(3)
        uf.union(0, 1)
        r1 = uf.find(0)
        r2 = uf.find(0)
        assert r1 == r2

    def test_transitive_union(self) -> None:
        """A~B and B~C → all three share the same root."""
        uf = UnionFind(3)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.find(0) == uf.find(1) == uf.find(2)

    def test_clusters_single_cluster(self) -> None:
        uf = UnionFind(3)
        uf.union(0, 1)
        uf.union(0, 2)
        clusters = uf.clusters()
        # There should be exactly one cluster containing all three members
        assert len(clusters) == 1
        sole_cluster = next(iter(clusters.values()))
        assert sorted(sole_cluster) == [0, 1, 2]

    def test_clusters_disjoint(self) -> None:
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(2, 3)
        clusters = uf.clusters()
        assert len(clusters) == 2
        sizes = sorted(len(v) for v in clusters.values())
        assert sizes == [2, 2]

    def test_clusters_no_unions(self) -> None:
        uf = UnionFind(3)
        clusters = uf.clusters()
        assert len(clusters) == 3
        for members in clusters.values():
            assert len(members) == 1

    def test_path_compression_does_not_change_membership(self) -> None:
        """Heavy chain, then find — path compression must not change cluster membership."""
        uf = UnionFind(5)
        for i in range(4):
            uf.union(i, i + 1)
        root = uf.find(4)
        # All nodes should point to the same root
        for i in range(5):
            assert uf.find(i) == root


# ---------------------------------------------------------------------------
# SemanticDeduplicator helpers
# ---------------------------------------------------------------------------


def _make_embedder(embeddings: np.ndarray) -> MagicMock:
    mock = MagicMock()
    mock.embed_batch.return_value = embeddings
    return mock


def _near_identical_embeddings(n: int, dim: int = EMBED_DIM) -> np.ndarray:
    """Return n nearly identical unit vectors."""
    base = np.ones((1, dim), dtype=np.float32)
    base /= np.linalg.norm(base)
    tiles = np.tile(base, (n, 1))
    rng = np.random.default_rng(0)
    tiles += rng.standard_normal(tiles.shape).astype(np.float32) * 1e-5
    return tiles


def _orthogonal_embeddings(n: int, dim: int = EMBED_DIM) -> np.ndarray:
    """Return n embeddings with pairwise cosine similarity well below any threshold."""
    rng = np.random.default_rng(1)
    return rng.standard_normal((n, dim)).astype(np.float32)


# ---------------------------------------------------------------------------
# SemanticDeduplicator.deduplicate
# ---------------------------------------------------------------------------


class TestSemanticDeduplicatorDeduplicate:
    def test_single_chunk_returns_unchanged(self) -> None:
        """deduplicate([single_chunk]) → ([single_chunk], [], {})."""
        chunk = make_chunk("c1", "hello world")
        dedup = SemanticDeduplicator(embedder=_make_embedder(np.zeros((1, EMBED_DIM), dtype=np.float32)))
        kept, removed, consolidated = dedup.deduplicate([chunk])
        assert kept == [chunk]
        assert removed == []
        assert consolidated == {}

    def test_empty_list_returns_unchanged(self) -> None:
        dedup = SemanticDeduplicator(embedder=_make_embedder(np.zeros((0, EMBED_DIM), dtype=np.float32)))
        kept, removed, consolidated = dedup.deduplicate([])
        assert kept == []
        assert removed == []
        assert consolidated == {}

    def test_no_near_duplicates_returns_all_chunks(self) -> None:
        """Chunks with very different embeddings are all kept."""
        chunks = make_chunks(4)
        embedder = _make_embedder(_orthogonal_embeddings(4))
        dedup = SemanticDeduplicator(embedder=embedder)
        kept, removed, consolidated = dedup.deduplicate(chunks)
        assert len(kept) == 4
        assert removed == []
        assert consolidated == {}

    def test_two_near_duplicate_chunks_one_removed(self) -> None:
        """Two near-identical chunks → one removed with SEMANTIC_NEAR_DUP reason."""
        chunk_a = make_chunk("ca", "content A", score=0.7)
        chunk_b = make_chunk("cb", "content B", score=0.9)
        embedder = _make_embedder(_near_identical_embeddings(2))
        dedup = SemanticDeduplicator(embedder=embedder)
        kept, removed, consolidated = dedup.deduplicate([chunk_a, chunk_b])
        assert len(kept) == 1
        assert len(removed) == 1
        assert removed[0].reason == RemovalReason.SEMANTIC_NEAR_DUP

    def test_higher_score_chunk_is_retained(self) -> None:
        """The chunk with the higher score is retained when two are near-duplicate."""
        chunk_low  = make_chunk("c_low",  "text", score=0.4)
        chunk_high = make_chunk("c_high", "text", score=0.9)
        embedder = _make_embedder(_near_identical_embeddings(2))
        dedup = SemanticDeduplicator(embedder=embedder)
        kept, removed, _ = dedup.deduplicate([chunk_low, chunk_high])
        assert kept[0].chunk_id == "c_high"
        assert removed[0].chunk_id == "c_low"
        assert removed[0].duplicate_of == "c_high"

    def test_transitive_cluster_produces_two_removed_records(self) -> None:
        """A~B, B~C (transitive) → one kept, two removed."""
        chunks = [
            make_chunk("ca", "A", score=0.5),
            make_chunk("cb", "B", score=0.9),  # highest score → retained
            make_chunk("cc", "C", score=0.6),
        ]
        embedder = _make_embedder(_near_identical_embeddings(3))
        dedup = SemanticDeduplicator(embedder=embedder)
        kept, removed, consolidated = dedup.deduplicate(chunks)
        assert len(kept) == 1
        assert kept[0].chunk_id == "cb"
        assert len(removed) == 2
        assert all(r.reason == RemovalReason.SEMANTIC_NEAR_DUP for r in removed)
        assert all(r.duplicate_of == "cb" for r in removed)

    def test_consolidated_maps_retained_to_absorbed_source_ids(self) -> None:
        """consolidated[retained_chunk_id] contains the source_ids of absorbed chunks."""
        chunk_a = make_chunk("ca", "A", source_id="src_a", score=0.5)
        chunk_b = make_chunk("cb", "B", source_id="src_b", score=0.9)
        embedder = _make_embedder(_near_identical_embeddings(2))
        dedup = SemanticDeduplicator(embedder=embedder)
        _, _, consolidated = dedup.deduplicate([chunk_a, chunk_b])
        assert "cb" in consolidated
        assert consolidated["cb"] == ["src_a"]

    def test_original_order_preserved_among_kept_chunks(self) -> None:
        """kept list preserves input order for non-duplicate chunks."""
        rng = np.random.default_rng(99)
        # 5 independent (low-similarity) embeddings
        embeddings = rng.standard_normal((5, EMBED_DIM)).astype(np.float32)
        chunks = make_chunks(5)
        embedder = _make_embedder(embeddings)
        dedup = SemanticDeduplicator(embedder=embedder)
        kept, _, _ = dedup.deduplicate(chunks)
        kept_ids = [c.chunk_id for c in kept]
        original_ids = [c.chunk_id for c in chunks if c.chunk_id in kept_ids]
        assert kept_ids == original_ids

    def test_removed_chunk_has_original_content(self) -> None:
        """RemovedChunk.original_content must match the absorbed chunk's content."""
        chunk_a = make_chunk("ca", "content of A", score=0.3)
        chunk_b = make_chunk("cb", "content of B", score=0.8)
        embedder = _make_embedder(_near_identical_embeddings(2))
        dedup = SemanticDeduplicator(embedder=embedder)
        _, removed, _ = dedup.deduplicate([chunk_a, chunk_b])
        assert removed[0].original_content == "content of A"

    def test_two_independent_pairs_both_deduplicated(self) -> None:
        """Two separate near-duplicate pairs each collapse to one chunk."""
        # Build embeddings: pair 0-1 near-identical, pair 2-3 near-identical,
        # but cross-pair similarity is low.
        rng = np.random.default_rng(7)
        base_01 = rng.standard_normal((1, EMBED_DIM)).astype(np.float32)
        base_23 = rng.standard_normal((1, EMBED_DIM)).astype(np.float32)
        # Ensure cross-pair dissimilarity
        base_23 -= np.dot(base_01, base_23.T) * base_01  # orthogonalise

        def _tile(base: np.ndarray) -> np.ndarray:
            t = np.tile(base, (2, 1))
            t += rng.standard_normal(t.shape).astype(np.float32) * 1e-5
            return t

        embeddings = np.vstack([_tile(base_01), _tile(base_23)])
        chunks = make_chunks(4)
        embedder = _make_embedder(embeddings)
        dedup = SemanticDeduplicator(embedder=embedder)
        kept, removed, _ = dedup.deduplicate(chunks)
        assert len(kept) == 2
        assert len(removed) == 2
