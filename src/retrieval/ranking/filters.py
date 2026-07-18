"""Post-scoring reduction functions for the Context Retrieval Engine (TASK-US014-03).

Provides two pure, stateless functions consumed by ``ContextRanker``:

- ``filter_below_threshold`` — drops chunks whose combined score is below a
  configurable minimum relevance threshold.
- ``truncate_to_token_budget`` — cuts the sorted chunk list to fit within an
  execution plan's token budget, keeping only whole chunks.
"""

from __future__ import annotations

import tiktoken

from src.retrieval.ranking.config import DEFAULT_RELEVANCE_THRESHOLD
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

_enc = tiktoken.get_encoding("cl100k_base")  # module-level singleton


def count_tokens(text: str) -> int:
    """Return the number of ``cl100k_base`` tokens in *text*."""
    return len(_enc.encode(text))


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


def filter_below_threshold(
    chunks: list[RetrievedChunk],
    threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
) -> list[RetrievedChunk]:
    """Exclude chunks whose ``score`` is strictly below *threshold*.

    Operates on the ``score`` field, which must already reflect the combined
    score written by ``ContextRanker`` before this function is called.

    Args:
        chunks: Scored chunks to filter.
        threshold: Minimum inclusive score to keep (default ``DEFAULT_RELEVANCE_THRESHOLD``).

    Returns:
        A new list containing only chunks with ``score >= threshold``.
    """
    return [c for c in chunks if c.score >= threshold]


# ---------------------------------------------------------------------------
# Token-budget truncation
# ---------------------------------------------------------------------------


def truncate_to_token_budget(
    chunks: list[RetrievedChunk],
    budget: int,
) -> list[RetrievedChunk]:
    """Return the longest prefix of *chunks* that fits within *budget* tokens.

    Chunks are assumed to be pre-sorted by descending score so the
    highest-relevance items are always retained.  Only complete chunks are
    included — no partial-content chunks.

    A single chunk whose token count exceeds *budget* results in an empty list
    rather than a ``RuntimeError``.

    Args:
        chunks: Pre-sorted (descending score) chunks to truncate.
        budget: Maximum total token count allowed.

    Returns:
        A new list containing the longest prefix of *chunks* within the budget.
    """
    kept: list[RetrievedChunk] = []
    used: int = 0
    for chunk in chunks:
        tokens = count_tokens(chunk.content)
        if used + tokens > budget:
            break
        kept.append(chunk)
        used += tokens
    return kept
