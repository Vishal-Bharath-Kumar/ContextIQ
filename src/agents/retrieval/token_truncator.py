"""Token-budget truncation helper for retrieval chunking.

TASK-US010-04: truncate_to_budget() — greedy front-loaded chunk selection
that never splits a chunk and never exceeds the allocated token quota.
"""
from __future__ import annotations

from src.llm.token_encoding import get_cl100k_encoding

# Module-level singleton — initialised once at import time.
# cl100k_base is the encoding used by GPT-3.5/GPT-4 and most hosted LLMs.
_enc = get_cl100k_encoding()


def truncate_to_budget(chunks: list[str], token_budget: int) -> list[str]:
    """Return chunks from the front of the list until ``token_budget`` is exhausted.

    Partial chunks are excluded; the caller receives only complete chunks that
    fit within the budget.  If the very first chunk already exceeds the budget,
    an empty list is returned.

    Args:
        chunks:       Ordered list of text chunks to consider.
        token_budget: Maximum number of tokens allowed in the returned list.

    Returns:
        A (possibly empty) prefix of ``chunks`` whose total token count does
        not exceed ``token_budget``.
    """
    kept: list[str] = []
    used = 0
    for chunk in chunks:
        chunk_tokens = len(_enc.encode(chunk))
        if used + chunk_tokens > token_budget:
            break
        kept.append(chunk)
        used += chunk_tokens
    return kept
