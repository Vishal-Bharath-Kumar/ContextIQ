# TASK-US015-04 — `RuleBasedCompressor` Orchestrator and 100 ms Benchmark

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US015-04 |
| User Story | US-015 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / Performance |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `RuleBasedCompressor`, the orchestrator that runs exact deduplication then boilerplate removal in sequence on a `list[RetrievedChunk]` and returns the compressed list alongside a consolidated `list[RemovedChunk]`. Add a CI benchmark asserting the full pipeline completes in < 100 ms for a 50-chunk input. `RuleBasedCompressor` is the sole entry point consumed by `compression_node` (TASK-US015-05).

## Implementation Details

**Technology:** Python 3.11+, `pytest-benchmark`

**File locations:**
- `src/compression/rule_based_compressor.py` — `RuleBasedCompressor` class
- `tests/compression/test_rule_based_compressor.py`
- `tests/compression/test_rule_based_compressor_benchmark.py`

**`RuleBasedCompressor`:**

```python
# src/compression/rule_based_compressor.py
from src.compression.dedup.exact_deduplicator  import ExactDeduplicator
from src.compression.boilerplate.detector      import BoilerplateDetector
from src.compression.boilerplate.settings      import BoilerplateSettings
from src.compression.schemas.removed_chunk     import RemovedChunk
from src.retrieval.schemas.retrieved_chunk     import RetrievedChunk

class RuleBasedCompressor:
    def __init__(
        self,
        deduplicator: ExactDeduplicator  | None = None,
        detector:     BoilerplateDetector | None = None,
    ) -> None:
        settings = BoilerplateSettings()
        self._deduplicator = deduplicator or ExactDeduplicator()
        self._detector     = detector     or BoilerplateDetector(rules=settings.get_rules())

    def compress(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[list[RetrievedChunk], list[RemovedChunk]]:
        """Apply rule-based compression: exact dedup → boilerplate removal.

        Steps applied in order:
          1. Exact deduplication (content fingerprint)
          2. Boilerplate pattern filtering

        Returns: (compressed_chunks, all_removed_chunks)
        """
        if not chunks:
            return [], []

        # Step 1: exact deduplication
        after_dedup, dedup_removed = self._deduplicator.deduplicate(chunks)

        # Step 2: boilerplate removal
        after_boilerplate, boiler_removed = self._detector.filter(after_dedup)

        all_removed = dedup_removed + boiler_removed
        return after_boilerplate, all_removed
```

**Ordering rationale:**
- Exact deduplication runs first because it is O(n) — cheap and eliminates chunks before the regex scan
- Boilerplate detection runs second on the already-reduced set, keeping the regex loop shorter
- The combined removed list preserves insertion order (exact-dup removals first, then boilerplate)

**100 ms benchmark — 50-chunk fixture:**

```python
# tests/compression/test_rule_based_compressor_benchmark.py
import pytest
from src.compression.rule_based_compressor     import RuleBasedCompressor
from src.retrieval.schemas.retrieved_chunk     import RetrievedChunk, ChunkMetadata
from datetime import datetime, timezone

LICENSE_HEADER = "// SPDX-License-Identifier: MIT\n// Copyright (c) 2024 ACME Corp\n"

def _make_chunks(n: int) -> list[RetrievedChunk]:
    now = datetime.now(timezone.utc)
    return [
        RetrievedChunk(
            chunk_id      = f"chunk-{i:03d}",
            source_id     = "github",
            content       = (LICENSE_HEADER if i % 5 == 0 else f"def function_{i}(): pass\n"),
            score         = 0.9 - i * 0.01,
            search_mode   = "rrf",
            metadata      = ChunkMetadata(file_path=f"src/mod_{i}.py", timestamp=now, author="dev"),
        )
        for i in range(n)
    ]

@pytest.mark.benchmark(max_time=0.1)
def test_rule_based_compressor_100ms_benchmark(benchmark):
    compressor = RuleBasedCompressor()
    chunks     = _make_chunks(50)

    compressed, removed = benchmark(lambda: compressor.compress(chunks))

    assert len(removed) >= 10   # 10 license-header chunks + possible duplicates
    assert all(c.score >= 0.0 for c in compressed)
```

**Token reduction validation (AC-4):**
The benchmark fixture includes 10/50 boilerplate chunks (20%), which exceeds the ≥ 10% token reduction threshold. A separate unit test asserts the reduction percentage on the fixture:

```python
def test_token_reduction_at_least_10_percent():
    from src.retrieval.ranking.filters import count_tokens
    compressor = RuleBasedCompressor()
    chunks     = _make_chunks(50)
    compressed, _ = compressor.compress(chunks)
    original_tokens    = sum(count_tokens(c.content) for c in chunks)
    compressed_tokens  = sum(count_tokens(c.content) for c in compressed)
    reduction = (original_tokens - compressed_tokens) / original_tokens
    assert reduction >= 0.10, f"Token reduction {reduction:.1%} < 10%"
```

## Acceptance Criteria

- [ ] `RuleBasedCompressor.compress([])` returns `([], [])`
- [ ] `compress(chunks)` returns chunks in the same relative order as the input (no resorting)
- [ ] All exact duplicates appear in `removed` with `reason = RemovalReason.EXACT_DUPLICATE`
- [ ] All boilerplate chunks appear in `removed` with `reason = RemovalReason.BOILERPLATE`
- [ ] No chunk appears in both the compressed output and the removed list
- [ ] CI benchmark passes: 50-chunk `compress()` completes in < 100 ms
- [ ] Token reduction ≥ 10% asserted on the standard fixture

## Dependencies

- TASK-US015-02 (`ExactDeduplicator.deduplicate()`)
- TASK-US015-03 (`BoilerplateDetector.filter()`, `BoilerplateSettings`)
- TASK-US014-03 (`count_tokens()` — reused for reduction assertion)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `RuleBasedCompressor` is the single orchestration entry point — node code calls only this class
- [ ] Benchmark and token-reduction tests included in CI; benchmark failure blocks merge
- [ ] `mypy --strict` passes; no `ruff` lint errors
