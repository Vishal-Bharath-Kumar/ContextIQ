# TASK-US017-04 — `ChunkSummarizer`: Parallel Batch Dispatch and 60% Reduction Eval Harness

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US017-04 |
| User Story | US-017 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / Performance |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement `ChunkSummarizer`, which identifies chunks exceeding the token threshold, fires `SummarizationChain.summarise()` calls concurrently (bounded by `max_concurrent`), replaces oversized content with summaries, and preserves sub-threshold chunks unchanged. Include the eval harness test that asserts ≥ 60% average token reduction and > 90% named-entity retention on a fixture corpus.

## Implementation Details

**Technology:** Python 3.11+, `asyncio`, `pytest`, `pytest-asyncio`

**File locations:**
- `src/compression/summarization/chunk_summarizer.py` — `ChunkSummarizer` class
- `tests/compression/summarization/test_chunk_summarizer.py`
- `tests/compression/summarization/test_chunk_summarizer_eval.py` — eval harness

**`ChunkSummarizer`:**

```python
# src/compression/summarization/chunk_summarizer.py
import asyncio
from src.retrieval.schemas.retrieved_chunk        import RetrievedChunk
from src.retrieval.ranking.filters                import count_tokens
from src.compression.summarization.chain          import SummarizationChain
from src.compression.summarization.settings       import get_summarization_settings

class ChunkSummarizer:
    def __init__(
        self,
        chain:     SummarizationChain | None = None,
        callbacks: list | None               = None,
    ) -> None:
        self._chain     = chain or SummarizationChain()
        self._settings  = get_summarization_settings()
        self._callbacks = callbacks or []

    async def summarize(
        self,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Summarise all chunks exceeding the token threshold.

        Sub-threshold chunks are passed through unchanged.
        On LLM failure for a specific chunk, the original is retained (fail-open).
        """
        if not chunks:
            return []

        threshold = self._settings.token_threshold
        semaphore = asyncio.Semaphore(self._settings.max_concurrent)

        async def _maybe_summarise(chunk: RetrievedChunk) -> RetrievedChunk:
            token_count = count_tokens(chunk.content)
            if token_count <= threshold:
                return chunk
            async with semaphore:
                try:
                    output = await self._chain.summarise(
                        content      = chunk.content,
                        input_tokens = token_count,
                        callbacks    = self._callbacks,
                    )
                    return chunk.model_copy(update={
                        "content":              output.summary,
                        "compressed":           True,
                        "original_token_count": token_count,
                    })
                except Exception:
                    # Fail-open: return original chunk on any LLM error
                    return chunk

        return list(await asyncio.gather(*[_maybe_summarise(c) for c in chunks]))
```

**Fail-open policy:**
If the LLM call for a specific chunk fails (timeout, rate limit, API error), `_maybe_summarise` returns the original chunk unchanged. This ensures the pipeline never fails entirely due to a single summarisation failure. The `compressed=False` flag on the returned chunk signals to downstream consumers that summarisation did not occur.

**Concurrency and rate-limit management:**
`asyncio.Semaphore(max_concurrent)` bounds the number of in-flight LLM calls. With `max_concurrent=10` (default), 10 chunks are summarised in parallel; remaining chunks wait in the asyncio event loop without blocking.

**Eval harness — 60% reduction and > 90% entity retention:**

```python
# tests/compression/summarization/test_chunk_summarizer_eval.py
"""
Eval harness for US-017 AC-4 and AC-5.
Uses deterministic mocked LLM responses built from a fixture corpus.
"""
import pytest, asyncio
from unittest.mock import AsyncMock, patch

# Fixture: 10 long chunks (~600 tokens each), each containing known entities
FIXTURE_CORPUS = [
    {
        "content":  "<600-token runbook text containing: HTTP 401, authenticate(), ACME Corp>",
        "entities": ["HTTP 401", "authenticate", "ACME Corp"],
        "summary":  "<240-token summary retaining all 3 entities>",
    },
    # ... 9 more entries
]

@pytest.mark.asyncio
async def test_60_percent_token_reduction():
    """Assert average token reduction ≥ 60% across the fixture corpus."""
    from src.retrieval.ranking.filters import count_tokens
    from src.compression.summarization.chunk_summarizer import ChunkSummarizer
    from src.compression.summarization.chain import SummarizationOutput

    def _mock_summarise(content, input_tokens, callbacks):
        idx = next(i for i, f in enumerate(FIXTURE_CORPUS) if f["content"][:20] in content)
        return SummarizationOutput(summary=FIXTURE_CORPUS[idx]["summary"],
                                   retained_entities=FIXTURE_CORPUS[idx]["entities"])

    with patch.object(SummarizationChain, "summarise", new=AsyncMock(side_effect=_mock_summarise)):
        summarizer = ChunkSummarizer()
        chunks     = [_make_chunk(f["content"]) for f in FIXTURE_CORPUS]
        result     = await summarizer.summarize(chunks)

    original_total   = sum(count_tokens(f["content"]) for f in FIXTURE_CORPUS)
    compressed_total = sum(count_tokens(c.content) for c in result)
    reduction = (original_total - compressed_total) / original_total
    assert reduction >= 0.60, f"Token reduction {reduction:.1%} < 60%"


@pytest.mark.asyncio
async def test_90_percent_entity_retention():
    """Assert > 90% of known entities appear in summaries across the fixture corpus."""
    # ... (similar structure: count entity hits across all summaries)
    retained_count = sum(
        1 for f in FIXTURE_CORPUS
        for e in f["entities"]
        if e in result_map[f["content"]].content
    )
    total_entities = sum(len(f["entities"]) for f in FIXTURE_CORPUS)
    retention_rate = retained_count / total_entities
    assert retention_rate > 0.90, f"Entity retention {retention_rate:.1%} ≤ 90%"
```

## Acceptance Criteria

- [ ] Chunks with `token_count ≤ threshold` are returned unchanged (`compressed=False`)
- [ ] Chunks with `token_count > threshold` are returned with `compressed=True` and `original_token_count` set
- [ ] On LLM failure for a specific chunk, the original chunk is returned (`compressed=False`) — no exception propagates
- [ ] At most `max_concurrent` LLM calls are in-flight simultaneously (semaphore verified via mock call timing)
- [ ] Eval harness: average token reduction ≥ 60% across the fixture corpus
- [ ] Eval harness: > 90% of known named entities appear in the resulting summaries
- [ ] All LLM calls mocked in tests — no live API calls in CI

## Dependencies

- TASK-US017-01 (`RetrievedChunk.compressed`, `original_token_count`)
- TASK-US017-02 (`SummarizationSettings.token_threshold`, `max_concurrent`)
- TASK-US017-03 (`SummarizationChain.summarise()`)
- TASK-US014-03 (`count_tokens()` — reused for token counting)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Eval harness tests committed to `tests/compression/summarization/test_chunk_summarizer_eval.py`
- [ ] Fail-open behaviour verified: mocked LLM raising `Exception` results in original chunk returned
- [ ] `asyncio.Semaphore` used — no unbounded `asyncio.gather` in production code
- [ ] `mypy --strict` passes; no `ruff` lint errors
