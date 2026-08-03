# TASK-US013-01 — Cache Key Derivation (`ContextCacheKey`)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US013-01 |
| User Story | US-013 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the deterministic cache key function that hashes the three inputs that uniquely identify a context retrieval request: the query embedding vector, the ordered source list, and the per-source token budget map. The resulting key is a short hex string used as the Redis field key for storage and lookup.

## Implementation Details

**Technology:** Python 3.11+, `hashlib` (stdlib)

**File locations:**
- `src/retrieval/cache/cache_key.py` — `make_cache_key()` function and `ContextCacheKey` named tuple
- `tests/retrieval/cache/test_cache_key.py`

**`ContextCacheKey` and `make_cache_key()`:**

```python
# src/retrieval/cache/cache_key.py
import hashlib, json
from typing import NamedTuple

class ContextCacheKey(NamedTuple):
    source_id:  str    # per-source — one cache entry per source per query
    hex_digest: str    # 16-char SHA-256 prefix (truncated for key length)

def make_cache_key(
    source_id:    str,
    query_vector: list[float],
    token_budget: int,
) -> ContextCacheKey:
    """Produce a deterministic cache key for a single-source retrieval request.

    Inputs:
        source_id    — connector identifier, e.g. "github"
        query_vector — embedding of the query prompt (list of floats)
        token_budget — token quota allocated to this source from ExecutionPlan
    """
    payload = json.dumps(
        {
            "v": [round(x, 6) for x in query_vector],   # round to 6 dp to absorb float noise
            "b": token_budget,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return ContextCacheKey(source_id=source_id, hex_digest=digest)

def redis_key(key: ContextCacheKey) -> str:
    """Format the Redis storage key including the source namespace prefix."""
    return f"ctx_cache:{key.source_id}:{key.hex_digest}"
```

**Design decisions:**

- **Per-source keys** — each `source_id` produces an independent cache entry so invalidation can target a single source without expiring results for others (`ctx_cache:{source_id}:*` glob pattern)
- **Source list excluded from key** — the caller (TASK-US013-03) iterates per source; each invocation of `make_cache_key` covers exactly one source, making multi-source plans naturally decomposed into independently cacheable units
- **Float rounding** — embedding vectors from `fastembed` are deterministic for the same input but floating-point arithmetic can introduce sub-ppm drift across platforms; rounding to 6 decimal places prevents false cache misses
- **Token budget included** — the same query with a different budget allocation must produce different results (fewer chunks), so budget is a key input

## Acceptance Criteria

- [ ] `make_cache_key("github", vector_a, 2000)` returns the same `hex_digest` on every call with identical inputs
- [ ] `make_cache_key("github", vector_a, 2000)` ≠ `make_cache_key("github", vector_a, 4000)` (budget change → different key)
- [ ] `make_cache_key("github", vector_a, 2000)` ≠ `make_cache_key("confluence", vector_a, 2000)` (source change → different key)
- [ ] `redis_key(key)` output matches pattern `ctx_cache:<source_id>:<16-char hex>`
- [ ] Rounding to 6 dp: vectors that differ by < 1e-7 in any dimension produce the same key

## Dependencies

- TASK-US012-02 (`QueryEmbedder.embed()` — produces the `query_vector` input)
- TASK-US010-01 (`ExecutionPlan.token_budget_per_source` — provides `token_budget` per source)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit tests cover: determinism, budget sensitivity, source sensitivity, float-rounding tolerance
- [ ] `make_cache_key` is a pure function with no side effects or I/O
- [ ] `mypy --strict` passes; no `ruff` lint errors
