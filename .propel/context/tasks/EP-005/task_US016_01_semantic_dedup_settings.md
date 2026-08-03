# TASK-US016-01 — `SemanticDedupSettings` Config and Threshold Constant

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US016-01 |
| User Story | US-016 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / Config |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the `SemanticDedupSettings` Pydantic settings model that exposes the similarity threshold and batch-size cap as admin-configurable values. The threshold (default 0.92) is the sole gate between near-duplicate pairs and retained chunks; making it externally configurable satisfies US-016 AC-6 without a code deploy.

## Implementation Details

**Technology:** Python 3.11+, `pydantic-settings`

**File locations:**
- `src/compression/semantic/settings.py` — `SemanticDedupSettings` and module-level singleton
- `tests/compression/semantic/test_settings.py`

**`SemanticDedupSettings`:**

```python
# src/compression/semantic/settings.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SEMANTIC_SIMILARITY_THRESHOLD: float = 0.92   # US-016 AC-2: retain when similarity ≥ this value
SEMANTIC_EMBED_BATCH_SIZE:      int   = 64     # max chunks per fastembed batch call

class SemanticDedupSettings(BaseSettings):
    """Admin-configurable parameters for semantic deduplication.

    Environment variables:
        SEMANTIC_DEDUP_THRESHOLD   — float in (0.0, 1.0], default 0.92
        SEMANTIC_DEDUP_BATCH_SIZE  — int ≥ 1, default 64
    """
    threshold:  float = Field(default=SEMANTIC_SIMILARITY_THRESHOLD, gt=0.0, le=1.0)
    batch_size: int   = Field(default=SEMANTIC_EMBED_BATCH_SIZE,     ge=1)

    model_config = SettingsConfigDict(
        env_prefix = "SEMANTIC_DEDUP_",
        env_file   = ".env",
    )

_settings: SemanticDedupSettings | None = None

def get_semantic_dedup_settings() -> SemanticDedupSettings:
    global _settings
    if _settings is None:
        _settings = SemanticDedupSettings()
    return _settings
```

**Why a separate settings module (not merged into `BoilerplateSettings`):**
Each compression stage has independent tuneable parameters. Keeping them in separate settings classes makes it possible to update the semantic threshold at runtime via a config-map reload without touching boilerplate settings — important for A/B testing threshold values in staging.

## Acceptance Criteria

- [ ] `SemanticDedupSettings()` loads `threshold = 0.92` and `batch_size = 64` by default
- [ ] `SEMANTIC_DEDUP_THRESHOLD=0.85` environment variable overrides the default
- [ ] `threshold = 0.0` raises `ValidationError` (`gt=0.0` constraint)
- [ ] `threshold = 1.01` raises `ValidationError` (`le=1.0` constraint)
- [ ] `get_semantic_dedup_settings()` returns the same instance on repeated calls (singleton)
- [ ] `SEMANTIC_SIMILARITY_THRESHOLD` constant is the default value source — no inline `0.92` literals in dedup code

## Dependencies

- TASK-US015-03 (`BoilerplateSettings` pattern — followed for consistency)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `SEMANTIC_SIMILARITY_THRESHOLD` and `SEMANTIC_EMBED_BATCH_SIZE` are documented in `docs/config/environment-variables.md`
- [ ] Unit tests cover: default load, env override, boundary validation
- [ ] `mypy --strict` passes; no `ruff` lint errors
