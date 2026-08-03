"""ContextAggregator — merge connector results into a unified context list.

TASK-US007-03: Aggregate ContextChunk lists from all successful connectors into
a single flat list, enforce per-source and global token budget caps, deduplicate
by chunk_id, and attach degraded_sources metadata for failed connectors.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.agents.retrieval.parallel_dispatcher import ContextChunk, FetchAllResult


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------


class DegradedSource(BaseModel):
    source_id: str
    error_type: str
    message: str


class AggregatedContext(BaseModel):
    chunks: list[ContextChunk]
    total_token_count: int
    source_count: int
    degraded_sources: list[DegradedSource]


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class ContextAggregator:
    """Merge, deduplicate, and budget-cap connector results.

    Per-source budget is applied first; then a global token cap is enforced
    across all sources combined.  Chunk deduplication is exact-match by
    ``chunk_id`` only (semantic dedup is deferred to EP-005).
    """

    def aggregate(
        self,
        fetch_result: FetchAllResult,
        token_budget_per_source: dict[str, int],
        global_token_budget: int,
    ) -> AggregatedContext:
        """Aggregate, deduplicate, and apply token budgets to connector results.

        Args:
            fetch_result:            Output from ``ParallelConnectorDispatcher.fetch_all``.
            token_budget_per_source: Optional per-source token caps; keyed by ``source_id``.
            global_token_budget:     Hard cap on total tokens across all sources combined.

        Returns:
            :class:`AggregatedContext` with the final deduplicated, budget-capped
            chunk list and the list of degraded (failed) sources.
        """
        chunks: list[ContextChunk] = []
        seen_chunk_ids: set[str] = set()

        # Per-source budget enforcement (preserves source insertion order)
        for source_id in self._source_order(fetch_result.chunks):
            source_chunks = [c for c in fetch_result.chunks if c.source_id == source_id]
            budget = token_budget_per_source.get(source_id, global_token_budget)
            accumulated = 0
            for chunk in source_chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                if accumulated + chunk.token_count > budget:
                    break
                chunks.append(chunk)
                seen_chunk_ids.add(chunk.chunk_id)
                accumulated += chunk.token_count

        # Global token cap across all sources combined
        global_chunks: list[ContextChunk] = []
        total_tokens = 0
        for chunk in chunks:
            if total_tokens + chunk.token_count > global_token_budget:
                break
            global_chunks.append(chunk)
            total_tokens += chunk.token_count

        return AggregatedContext(
            chunks=global_chunks,
            total_token_count=total_tokens,
            source_count=len({c.source_id for c in global_chunks}),
            degraded_sources=[
                DegradedSource(
                    source_id=f.source_id,
                    error_type=f.error_type,
                    message=f.message,
                )
                for f in fetch_result.failed_sources
            ],
        )

    @staticmethod
    def _source_order(chunks: list[ContextChunk]) -> list[str]:
        """Return source IDs in first-seen insertion order."""
        seen: dict[str, None] = dict.fromkeys(c.source_id for c in chunks)
        return list(seen)
