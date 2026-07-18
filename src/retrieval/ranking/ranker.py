"""ContextRanker orchestrator for the Context Retrieval Engine (TASK-US014-04).

Single entry point that orchestrates the full re-ranking pipeline:
  1. Score each chunk with the combined formula.
  2. Rebuild frozen chunk instances with updated scores.
  3. Filter below relevance threshold.
  4. Sort descending by score.
  5. Truncate to token budget.

Consumed by ``governance_node`` (TASK-US014-05).
"""

from __future__ import annotations

from src.retrieval.ranking.config import DEFAULT_RELEVANCE_THRESHOLD
from src.retrieval.ranking.filters import filter_below_threshold, truncate_to_token_budget
from src.retrieval.ranking.scorer import calculate_combined_score
from src.retrieval.ranking.weights import DEFAULT_WEIGHTS, RankingWeights
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk


class ContextRanker:
    """Stateless re-ranking orchestrator.

    Args:
        weights: Per-signal weights for the combined scoring formula.
        threshold: Minimum combined score to retain a chunk.
    """

    def __init__(
        self,
        weights: RankingWeights = DEFAULT_WEIGHTS,
        threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    ) -> None:
        self._weights = weights
        self._threshold = threshold

    def rank(
        self,
        chunks: list[RetrievedChunk],
        token_budget: int,
    ) -> list[RetrievedChunk]:
        """Score, filter, sort, and truncate a raw chunk list.

        Steps:
          1. Compute combined score for each chunk (vector + keyword + recency).
          2. Rebuild chunks with updated ``score`` field (model_copy — frozen model).
          3. Filter below threshold.
          4. Sort descending by score.
          5. Truncate to token budget.

        Args:
            chunks: Raw retrieved chunks from the search paths.
            token_budget: Maximum total token count for the returned context.

        Returns:
            Re-ranked and truncated list of chunks; never mutates input.
        """
        if not chunks:
            return []

        # Steps 1–2: score and rebuild (pure computation — no I/O)
        scored = [
            chunk.model_copy(update={"score": calculate_combined_score(chunk, self._weights)})
            for chunk in chunks
        ]

        # Step 3: threshold filter
        filtered = filter_below_threshold(scored, self._threshold)

        # Step 4: sort descending by score
        filtered.sort(key=lambda c: c.score, reverse=True)

        # Step 5: token budget truncation
        return truncate_to_token_budget(filtered, token_budget)
