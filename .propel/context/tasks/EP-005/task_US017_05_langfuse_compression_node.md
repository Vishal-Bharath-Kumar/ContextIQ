# TASK-US017-05 — Langfuse Cost Tracking and `compression_node` Stage 3 Integration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US017-05 |
| User Story | US-017 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / Observability |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Wire a Langfuse `CallbackHandler` into `SummarizationChain` so every LLM summarisation call is traced with token usage and inferred cost. Extend `compression_node()` with Stage 3 (`ChunkSummarizer`) and pass the per-request Langfuse trace context so all summarisation spans roll up under the same request trace.

## Implementation Details

**Technology:** Python 3.11+, `langfuse>=2.0`, `langchain`

**File locations:**
- `src/compression/summarization/langfuse_handler.py` — Langfuse callback factory
- `src/agents/nodes/compression_node.py` — Stage 3 added (extends TASK-US016-05)
- `tests/compression/summarization/test_langfuse_integration.py`

**Langfuse callback factory:**

```python
# src/compression/summarization/langfuse_handler.py
from langfuse.callback import CallbackHandler
from src.compression.summarization.settings import get_summarization_settings
from src.gateway.config import Settings

_settings = Settings()

def make_langfuse_handler(
    request_id: str,
    user_id:    str,
    session_id: str,
) -> CallbackHandler | None:
    """Return a configured Langfuse CallbackHandler, or None if disabled.

    The handler is created per-request so each trace carries the correct
    request_id, user_id, and session_id for cost attribution.
    """
    if not get_summarization_settings().langfuse_enabled:
        return None

    return CallbackHandler(
        public_key  = _settings.langfuse_public_key,
        secret_key  = _settings.langfuse_secret_key,
        host        = _settings.langfuse_host,
        trace_name  = "context_summarization",
        metadata    = {
            "request_id": request_id,
            "user_id":    user_id,
            "session_id": session_id,
        },
        tags        = ["compression", "summarization"],
    )
```

**Environment variables required:**

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
SUMMARIZATION_LANGFUSE_ENABLED=true
```

**Extended `compression_node()` — Stage 3:**

```python
# src/agents/nodes/compression_node.py  (extends TASK-US016-05)
from src.compression.rule_based_compressor           import RuleBasedCompressor
from src.compression.semantic.semantic_deduplicator  import SemanticDeduplicator
from src.compression.summarization.chunk_summarizer  import ChunkSummarizer
from src.compression.summarization.langfuse_handler  import make_langfuse_handler
from src.agents.state                                import AgentState, ExecutionStatus

_rule_compressor = RuleBasedCompressor()    # module-level singletons
_semantic_dedup  = SemanticDeduplicator()
# ChunkSummarizer is NOT a singleton — it receives per-request Langfuse callbacks

async def compression_node(state: AgentState) -> dict:
    ranked_context = state.get("ranked_context") or []
    request_id     = state["request_id"]
    user_id        = state["user_id"]

    # Stage 1: rule-based (exact dedup + boilerplate) — US-015
    after_rules, rule_removed = _rule_compressor.compress(ranked_context)

    # Stage 2: semantic near-duplicate merging — US-016
    after_semantic, semantic_removed, consolidated = _semantic_dedup.deduplicate(after_rules)

    # Stage 3: LLM summarisation of oversized chunks — US-017
    langfuse_handler = make_langfuse_handler(
        request_id = request_id,
        user_id    = user_id,
        session_id = request_id,   # reuse request_id as session for trace grouping
    )
    callbacks   = [langfuse_handler] if langfuse_handler else []
    summarizer  = ChunkSummarizer(callbacks=callbacks)
    after_summarization = await summarizer.summarize(after_semantic)

    all_removed = rule_removed + semantic_removed

    return {
        "compressed_context":  after_summarization,
        "removed_chunks":      all_removed,
        "consolidated_sources": consolidated if consolidated else None,
        "ranked_context":      after_summarization,
        "current_node":        "compression_agent",
        "status":              ExecutionStatus.RUNNING,
    }
```

**Langfuse trace structure:**

Each request with summarisation produces a Langfuse trace tree:
```
Trace: context_summarization (request_id=<uuid>)
  └─ Generation: gpt-4o-mini   input_tokens=623, output_tokens=241, cost=$0.000124
  └─ Generation: gpt-4o-mini   input_tokens=812, output_tokens=305, cost=$0.000162
  ...
```

Cost is inferred by Langfuse automatically from the model name and token counts reported by the OpenAI API.

**`SUMMARIZATION_LANGFUSE_ENABLED=false` guard:**
When Langfuse is disabled (e.g. in CI or local dev), `make_langfuse_handler` returns `None` and `callbacks=[]`. No Langfuse imports execute at call time — only the factory import is loaded at module level.

**`ChunkSummarizer` per-request instantiation rationale:**
Unlike the compressor singletons, `ChunkSummarizer` receives per-request Langfuse callbacks and cannot be a module-level singleton. Its construction cost is negligible (no model loading) — only `SummarizationChain` (and its LLM client) is expensive, and that IS a singleton inside the chain.

## Acceptance Criteria

- [ ] Every `SummarizationChain.summarise()` call receives the Langfuse `CallbackHandler` via the `callbacks` argument
- [ ] A Langfuse trace is created per `compression_node` invocation containing all summarisation generations
- [ ] `SUMMARIZATION_LANGFUSE_ENABLED=false` disables tracing without errors or log warnings
- [ ] `compression_node` runs all three stages in order: rule-based → semantic → summarisation
- [ ] Missing Langfuse credentials (`LANGFUSE_PUBLIC_KEY` not set) raises `ValidationError` at startup when `langfuse_enabled=True`
- [ ] `ChunkSummarizer` is instantiated per call (not singleton); `SummarizationChain` inside it is a singleton

## Dependencies

- TASK-US016-05 (`compression_node` two-stage implementation — extended here with Stage 3)
- TASK-US017-04 (`ChunkSummarizer.summarize()`)
- TASK-US017-03 (`SummarizationChain` — receives callbacks from this task)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Langfuse credentials documented in `docs/config/environment-variables.md` with a `required: true` flag
- [ ] Unit test verifies Langfuse handler is passed to the chain when enabled, and not passed when disabled
- [ ] Integration test (mocked Langfuse client) verifies trace metadata contains `request_id` and `user_id`
- [ ] `mypy --strict` passes; no `ruff` lint errors
