"""SemanticDeduplicator: batch embedding, similarity matrix, union-find cluster resolution."""

from __future__ import annotations

import numpy as np

from src.compression.schemas.removed_chunk import RemovalReason, RemovedChunk
from src.compression.semantic.settings import get_semantic_dedup_settings
from src.compression.semantic.similarity import compute_similarity_matrix, find_near_duplicate_pairs
from src.retrieval.embedding.embedder import QueryEmbedder
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


class UnionFind:
    """Union-find (disjoint set) with path compression and union-by-rank."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank   = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def clusters(self) -> dict[int, list[int]]:
        """Return root → [member indices] mapping."""
        result: dict[int, list[int]] = {}
        for i in range(len(self._parent)):
            root = self.find(i)
            result.setdefault(root, []).append(i)
        return result


class SemanticDeduplicator:
    """Orchestrates batch embedding, similarity matrix, union-find cluster resolution, and merge-by-score."""

    def __init__(self, embedder: QueryEmbedder | None = None) -> None:
        self._embedder = embedder or QueryEmbedder.get()
        self._settings = get_semantic_dedup_settings()

    def deduplicate(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[list[RetrievedChunk], list[RemovedChunk], dict[str, list[str]]]:
        """Detect and remove semantically near-duplicate chunks.

        Returns:
            kept         — deduplicated chunk list (order preserved from input)
            removed      — RemovedChunk records for merged-away chunks
            consolidated — retained_chunk_id → list of absorbed source_ids
        """
        if len(chunks) < 2:
            return list(chunks), [], {}

        # 1. Batch embed all chunk contents
        texts      = [c.content for c in chunks]
        embeddings: np.ndarray = self._embedder.embed_batch(texts)  # (n, 384)

        # 2. Compute pairwise cosine similarity matrix
        sim_matrix = compute_similarity_matrix(embeddings)  # (n, n)

        # 3. Find near-duplicate pairs
        pairs = find_near_duplicate_pairs(sim_matrix, self._settings.threshold)

        if not pairs:
            return list(chunks), [], {}

        # 4. Build clusters via union-find
        uf = UnionFind(len(chunks))
        for i, j in pairs:
            uf.union(i, j)

        # 5. Per cluster: retain highest-scored chunk, remove the rest
        kept:         list[RetrievedChunk]  = []
        removed:      list[RemovedChunk]    = []
        consolidated: dict[str, list[str]] = {}

        for _root, members in uf.clusters().items():
            if len(members) == 1:
                kept.append(chunks[members[0]])
                continue

            # Choose the member with the highest relevance score
            best_idx       = max(members, key=lambda i: chunks[i].score)
            retained_chunk = chunks[best_idx]
            kept.append(retained_chunk)

            # Record absorbed source IDs
            absorbed_sources = [chunks[i].source_id for i in members if i != best_idx]
            if absorbed_sources:
                consolidated[retained_chunk.chunk_id] = absorbed_sources

            # Build RemovedChunk records for the rest
            for i in members:
                if i == best_idx:
                    continue
                removed.append(
                    RemovedChunk(
                        chunk_id         = chunks[i].chunk_id,
                        source_id        = chunks[i].source_id,
                        reason           = RemovalReason.SEMANTIC_NEAR_DUP,
                        duplicate_of     = retained_chunk.chunk_id,
                        original_content = chunks[i].content,
                    )
                )

        # Preserve original order among kept chunks
        chunk_order = {ch.chunk_id: idx for idx, ch in enumerate(chunks)}
        kept.sort(key=lambda c: chunk_order[c.chunk_id])

        return kept, removed, consolidated
