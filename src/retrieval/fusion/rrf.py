"""Reciprocal Rank Fusion (RRF) merger for hybrid vector + keyword search.

Reference: Cormack, Clarke & Buettcher (2009) — "Reciprocal Rank Fusion outperforms
Condorcet and individual Rank Learning Methods".
"""

from __future__ import annotations

from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

DEFAULT_K: int = 60  # RRF smoothing constant (Cormack et al., 2009)
DEFAULT_TOP_K: int = 20  # returned result set size (US-012 AC-3)


class ReciprocRankFusion:
    """Merge N independently-ranked ``RetrievedChunk`` lists via RRF scoring.

    RRF score for document *d*:

        RRF(d) = sum_{l in L} 1 / (k + r_l(d))

    where *k* is the smoothing constant and *r_l(d)* is the 1-indexed rank of
    *d* in list *l*.  Chunks absent from a list contribute nothing to their
    score from that list.
    """

    def __init__(self, k: int = DEFAULT_K, top_k: int = DEFAULT_TOP_K) -> None:
        self._k = k
        self._top_k = top_k

    def merge(
        self,
        *ranked_lists: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Merge N ranked lists into one top-K list using RRF scoring.

        Chunks with the same ``chunk_id`` across lists are deduplicated;
        the instance with the highest individual score is retained for the
        content payload.
        """
        rrf_scores: dict[str, float] = {}
        best_chunk: dict[str, RetrievedChunk] = {}
        vector_scores: dict[str, float] = {}
        keyword_scores: dict[str, float] = {}

        for ranked_list in ranked_lists:
            for rank, chunk in enumerate(ranked_list, start=1):
                cid = chunk.chunk_id
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (self._k + rank)
                if chunk.search_mode == "vector":
                    vector_scores[cid] = chunk.score
                elif chunk.search_mode == "keyword":
                    keyword_scores[cid] = chunk.score
                if cid not in best_chunk or chunk.score > best_chunk[cid].score:
                    best_chunk[cid] = chunk

        merged = [
            best_chunk[cid].model_copy(
                update={
                    "score": rrf_score,
                    "search_mode": "rrf",
                    "vector_score": vector_scores.get(cid),
                    "keyword_score": keyword_scores.get(cid),
                }
            )
            for cid, rrf_score in rrf_scores.items()
        ]

        merged.sort(key=lambda c: c.score, reverse=True)
        return merged[: self._top_k]


def rrf_merge(
    vector_results: list[RetrievedChunk],
    keyword_results: list[RetrievedChunk],
    k: int = DEFAULT_K,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Convenience wrapper for two-list hybrid search merge."""
    return ReciprocRankFusion(k=k, top_k=top_k).merge(vector_results, keyword_results)
