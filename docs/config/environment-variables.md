# Environment Variables

Reference for all runtime-configurable environment variables exposed by ContextIQ services.

---

## Semantic Deduplication (`src/compression/semantic`)

| Variable | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `SEMANTIC_DEDUP_THRESHOLD` | `float` | `0.92` | `(0.0, 1.0]` | Cosine-similarity threshold above which two chunks are considered near-duplicates. US-016 AC-2: a chunk is retained when its similarity to a prior chunk is below this value. |
| `SEMANTIC_DEDUP_BATCH_SIZE` | `int` | `64` | `>= 1` | Maximum number of chunks submitted to the fastembed model in a single batch call. |

### Usage

```bash
# Raise the threshold to only drop very close duplicates
SEMANTIC_DEDUP_THRESHOLD=0.97

# Reduce batch size for memory-constrained environments
SEMANTIC_DEDUP_BATCH_SIZE=16
```

### Constants

The module-level constants are the authoritative default sources and must be used wherever
the values are referenced in production code — never use inline numeric literals.

| Constant | Value | Location |
|---|---|---|
| `SEMANTIC_SIMILARITY_THRESHOLD` | `0.92` | `src/compression/semantic/settings.py` |
| `SEMANTIC_EMBED_BATCH_SIZE` | `64` | `src/compression/semantic/settings.py` |

---

## Summarisation (`src/compression/summarization`)

| Variable | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `SUMMARIZATION_TOKEN_THRESHOLD` | `int` | `500` | `>= 1` | Chunks whose token count exceeds this value are sent to the LLM for summarisation. US-017 AC-1. |
| `SUMMARIZATION_MODEL_NAME` | `str` | `"gpt-4o-mini"` | non-empty string | LLM model identifier used for summarisation. Set to an EP-006 model-router endpoint to enable dynamic routing without code changes. |
| `SUMMARIZATION_TARGET_RATIO` | `float` | `0.40` | `(0.0, 1.0)` | Target compression ratio: the summary should be at most this fraction of the original token count (e.g. `0.40` = 60% reduction). |
| `SUMMARIZATION_MAX_OUTPUT_TOKENS` | `int` | `400` | `>= 50` | Maximum tokens the LLM may emit per summarisation call. Prevents runaway cost on large chunks. |
| `SUMMARIZATION_MAX_CONCURRENT` | `int` | `10` | `>= 1` | Maximum number of concurrent LLM summarisation calls allowed via `asyncio.Semaphore`. Prevents upstream rate-limit errors when many chunks require summarisation in a single request. |
| `SUMMARIZATION_LANGFUSE_ENABLED` | `bool` | `True` | `true`/`false` | Enable Langfuse observability tracing for summarisation LLM calls. |

### Usage

```bash
# Lower the threshold so shorter chunks are also summarised
SUMMARIZATION_TOKEN_THRESHOLD=300

# Switch to a more capable model
SUMMARIZATION_MODEL_NAME=gpt-4o

# Tighten the compression target to 30%
SUMMARIZATION_TARGET_RATIO=0.30

# Reduce concurrency to avoid rate limits in low-quota environments
SUMMARIZATION_MAX_CONCURRENT=5
```

### Constants

| Constant | Value | Location |
|---|---|---|
| `SUMMARIZATION_TOKEN_THRESHOLD` | `500` | `src/compression/summarization/settings.py` |
| `SUMMARIZATION_TARGET_RATIO` | `0.40` | `src/compression/summarization/settings.py` |
| `SUMMARIZATION_MAX_OUTPUT_TOKENS` | `400` | `src/compression/summarization/settings.py` |

---

## Langfuse Observability (`src/observability/cost`, `src/compression/summarization`)

| Variable | Type | Required | Default | Description |
|---|---|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | `str` | `true` (when `SUMMARIZATION_LANGFUSE_ENABLED=true`) | — | Langfuse project public key (`pk-lf-…`). Must be set when Langfuse tracing is enabled; omitting it raises `ValidationError` at application startup. |
| `LANGFUSE_SECRET_KEY` | `str` | `true` (when `SUMMARIZATION_LANGFUSE_ENABLED=true`) | — | Langfuse project secret key (`sk-lf-…`). Required alongside `LANGFUSE_PUBLIC_KEY`. |
| `LANGFUSE_HOST` | `str` | `false` | `https://cloud.langfuse.com` | Langfuse server URL. Override for self-hosted deployments. |

### Usage

```bash
# Cloud Langfuse (default host)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# Self-hosted Langfuse instance
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://langfuse.internal.example.com

# Disable Langfuse tracing (e.g. CI, local dev)
SUMMARIZATION_LANGFUSE_ENABLED=false
```

### Notes

- `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are consumed by both the LLM cost recorder (`src/observability/cost/recorder.py`) and the summarisation Langfuse handler (`src/compression/summarization/langfuse_handler.py`).
- Setting `SUMMARIZATION_LANGFUSE_ENABLED=false` disables tracing for the summarisation stage only. Cost recorder tracing is controlled independently by `LLMCostRecorder` initialisation.
