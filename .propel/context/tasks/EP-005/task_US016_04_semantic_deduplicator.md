# TASK-US016-04 — `SemanticDeduplicator`: Cluster Resolution, Merge Strategy, and 300 ms Benchmark

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US016-04 |
| User Story | US-016 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / Performance |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `SemanticDeduplicator`, the class that orchestrates batch embedding, similarity matrix computation, union-find cluster resolution for transitive near-duplicates, and merge-by-score to produce the final deduplicated chunk list. Add a CI benchmark asserting the complete pipeline runs in < 300 ms for 50 chunks (with mocked embedding latency at the p95 expected value).

## Implementation Details

**Technology:** Python 3.11+, `numpy>=1.26`

**File locations:**
- `src/compression/semantic/semantic_deduplicator.py` — `SemanticDeduplicator` class and `UnionFind`
- `tests/compression/semantic/test_semantic_deduplicator.py`
- `tests/compression/semantic/test_semantic_deduplicator_benchmark.py`

**`UnionFind` for transitive cluster resolution:**

A~B and B~C detected as separate pairs; union-find merges them into cluster {A, B, C} so only one representative is kept rather than keeping B when it should be subsumed.

```python
# src/compression/semantic/semantic_deduplicator.py
class UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank   = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]   # path compression
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
```

**`SemanticDeduplicator`:**

```python
import numpy as np
from src.retrieval.embedding.embedder          import QueryEmbedder
from src.retrieval.schemas.retrieved_chunk     import RetrievedChunk
from src.compression.schemas.removed_chunk     import RemovedChunk, RemovalReason
from src.compression.semantic.settings         import get_semantic_dedup_settings
from src.compression.semantic.similarity       import compute_similarity_matrix, find_near_duplicate_pairs

class SemanticDeduplicator:
    def __init__(self, embedder: QueryEmbedder | None = None) -> None:
        self._embedder  = embedder or QueryEmbedder.get()
        self._settings  = get_semantic_dedup_settings()

    def deduplicate(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[list[RetrievedChunk], list[RemovedChunk], dict[str, list[str]]]:
        """Detect and remove semantically near-duplicate chunks.

        Returns:
            kept            — deduplicated chunk list (order preserved from input)
            removed         — RemovedChunk records for merged-away chunks
            consolidated    — retained_chunk_id → list of absorbed source_ids
        """
        if len(chunks) < 2:
            return list(chunks), [], {}

        # 1. Batch embed all chunk contents
        texts      = [c.content for c in chunks]
        embeddings = self._embedder.embed_batch(texts)          # (n, 384)

        # 2. Compute similarity matrix
        sim_matrix = compute_similarity_matrix(embeddings)      # (n, n)

        # 3. Find near-duplicate pairs
        pairs = find_near_duplicate_pairs(sim_matrix, self._settings.threshold)

        if not pairs:
            return list(chunks), [], {}

        # 4. Build clusters via union-find
        uf = UnionFind(len(chunks))
        for i, j in pairs:
            uf.union(i, j)

        # 5. Per cluster: retain highest-scored chunk, remove the rest
        kept:          list[RetrievedChunk]           = []
        removed:       list[RemovedChunk]             = []
        consolidated:  dict[str, list[str]]           = {}
        retained_set:  set[int]                       = set()

        for root, members in uf.clusters().items():
            if len(members) == 1:
                kept.append(chunks[members[0]])
                retained_set.add(members[0])
                continue

            # Choose the member with the highest relevance score
            best_idx = max(members, key=lambda i: chunks[i].score)
            retained_chunk   = chunks[best_idx]
            retained_set.add(best_idx)
            kept.append(retained_chunk)

            # Record absorbed source IDs
            absorbed_sources = [
                chunks[i].source_id for i in members if i != best_idx
            ]
            if absorbed_sources:
                consolidated[retained_chunk.chunk_id] = absorbed_sources

            # Build RemovedChunk records for the rest
            for i in members:
                if i == best_idx:
                    continue
                removed.append(RemovedChunk(
                    chunk_id         = chunks[i].chunk_id,
                    source_id        = chunks[i].source_id,
                    reason           = RemovalReason.SEMANTIC_NEAR_DUP,
                    duplicate_of     = retained_chunk.chunk_id,
                    original_content = chunks[i].content,
                ))

        # Preserve original order among kept chunks
        kept.sort(key=lambda c: next(
            idx for idx, ch in enumerate(chunks) if ch.chunk_id == c.chunk_id
        ))
        return kept, removed, consolidated
```

**300 ms benchmark:**

```python
# tests/compression/semantic/test_semantic_deduplicator_benchmark.py
import pytest, numpy as np
from unittest.mock import MagicMock, patch

CHUNK_COUNT = 50
EMBED_DIM   = 384

def _mock_embeddings(n: int) -> np.ndarray:
    """Produce n/5 clusters of 5 near-identical vectors to guarantee ≥ 15% reduction."""
    rng = np.random.default_rng(42)
    base = rng.standard_normal((n // 5, EMBED_DIM)).astype(np.float32)
    # Tile each base vector 5 times with tiny noise → similarity > 0.99
    tiles = np.repeat(base, 5, axis=0)
    tiles += rng.standard_normal(tiles.shape).astype(np.float32) * 0.001
    return tiles[:n]

@pytest.mark.benchmark(max_time=0.3)
def test_semantic_dedup_300ms_benchmark(benchmark):
    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = _mock_embeddings(CHUNK_COUNT)

    from tests.compression.semantic.fixtures import make_chunks
    chunks = make_chunks(CHUNK_COUNT)
    deduplicator = SemanticDeduplicator(embedder=mock_embedder)

    kept, removed, _ = benchmark(lambda: deduplicator.deduplicate(chunks))
    assert len(kept) < CHUNK_COUNT        # at least one cluster was merged
    assert len(removed) >= CHUNK_COUNT // 5 * 4   # 4 of 5 per cluster removed
```

## Acceptance Criteria

- [ ] Two chunks with cosine similarity ≥ 0.92 result in one being removed with `reason = SEMANTIC_NEAR_DUP`
- [ ] The retained chunk in a pair is always the one with the higher `score`
- [ ] Transitive clusters (A~B, B~C with threshold 0.92) produce one retained chunk and two `RemovedChunk` records
- [ ] `deduplicate(chunks)` with no near-duplicate pairs returns `(chunks, [], {})`
- [ ] `deduplicate([single_chunk])` returns `([single_chunk], [], {})`
- [ ] `consolidated` maps retained `chunk_id` → list of absorbed `source_id` values
- [ ] CI benchmark passes: 50-chunk `deduplicate()` with mocked embedding completes in < 300 ms

## Dependencies

- TASK-US016-01 (`get_semantic_dedup_settings()` — threshold and batch size)
- TASK-US016-02 (`QueryEmbedder.embed_batch()`)
- TASK-US016-03 (`compute_similarity_matrix()`, `find_near_duplicate_pairs()`)
- TASK-US015-01 (`RemovedChunk`, `RemovalReason.SEMANTIC_NEAR_DUP`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `UnionFind` path compression implemented — no O(n²) find operations in the cluster step
- [ ] Unit tests cover: single pair, transitive cluster, no pairs, single chunk, score-based retention
- [ ] Benchmark test included in CI; failure blocks merge
- [ ] `mypy --strict` passes; no `ruff` lint errors
