"""Cache key derivation for context retrieval requests.

Each source produces an independent cache entry keyed by the query vector
and the token budget allocated to that source. This allows per-source cache
invalidation without expiring results for other sources.
"""

from __future__ import annotations

import hashlib
import json
from typing import NamedTuple


class ContextCacheKey(NamedTuple):
    source_id: str  # connector identifier, e.g. "github"
    hex_digest: str  # 16-char SHA-256 prefix (truncated for key length)


def make_cache_key(
    source_id: str,
    query_vector: list[float],
    token_budget: int,
) -> ContextCacheKey:
    """Produce a deterministic cache key for a single-source retrieval request.

    Args:
        source_id:    Connector identifier, e.g. ``"github"``.
        query_vector: Embedding of the query prompt (list of floats).
        token_budget: Token quota allocated to this source from ExecutionPlan.

    Returns:
        A :class:`ContextCacheKey` whose ``hex_digest`` is a 16-character
        SHA-256 prefix that is stable across calls with identical inputs.
    """
    payload = json.dumps(
        {
            "v": [round(x, 6) for x in query_vector],  # round to 6 dp to absorb float noise
            "b": token_budget,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return ContextCacheKey(source_id=source_id, hex_digest=digest)


def redis_key(key: ContextCacheKey) -> str:
    """Format the Redis storage key including the source namespace prefix.

    Pattern: ``ctx_cache:<source_id>:<hex_digest>``

    The ``ctx_cache:<source_id>:*`` glob can be used to invalidate all cached
    results for a single source without affecting other sources.
    """
    return f"ctx_cache:{key.source_id}:{key.hex_digest}"
