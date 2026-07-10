# TASK-US028-02 — `EntityExtractor`: LiteLLM JSON Extraction with 500 ms Budget

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US028-02 |
| User Story | US-028 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `EntityExtractor` — the component that accepts a `ChunkIndexedEvent`, calls `litellm.acompletion()` with a structured JSON system prompt, parses the response into a list of `ExtractedEntity` objects, and returns an `EntityExtractionResult`. Satisfies AC-2 (7 entity types), AC-5 (≤ 500 ms average per chunk), and the extraction leg of AC-6 (errors surfaced to caller for retry).

## Implementation Details

**Technology:** Python 3.11+, LiteLLM `>=1.30`, LangChain (`ChatPromptTemplate`, `JsonOutputParser`), Pydantic v2, `pydantic-settings`, `asyncio`

**File locations:**
- `src/knowledge_graph/extraction/extractor.py` — `EntityExtractor`, `ExtractionSettings`
- `src/knowledge_graph/extraction/prompts.py` — `ENTITY_EXTRACTION_PROMPT`
- `tests/knowledge_graph/test_entity_extractor.py`

---

### `ExtractionSettings`

```python
# src/knowledge_graph/extraction/extractor.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class ExtractionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENTITY_EXTRACTION_", env_file=".env")

    # AIR-020 specifies the extraction model; default is a fast, cheap model.
    model_id:           str   = "gpt-4o-mini"
    # Hard timeout per LiteLLM call. Keeps p99 latency from blowing past the 500 ms SLA.
    timeout_s:          float = 2.0
    # Temperature 0 for deterministic, reproducible entity extraction.
    temperature:        float = 0.0
    # Max tokens in the LLM response; limits cost and prevents runaway outputs.
    max_tokens:         int   = 512
```

---

### Extraction prompt

```python
# src/knowledge_graph/extraction/prompts.py
ENTITY_EXTRACTION_SYSTEM = """\
You are an expert at extracting named entities from engineering documentation.
Extract all entities of the following types from the provided chunk of text.

Entity types:
- Service: A software service, API, microservice, or platform component.
- Repository: A code repository (GitHub, GitLab, Bitbucket, etc.).
- Developer: A person who is a developer, engineer, team lead, or on-call responder.
- Incident: A production incident, outage, or SLO breach.
- Deployment: A deployment event, release, or rollout.
- AlertRule: A monitoring alert rule or PagerDuty policy.
- Document: A wiki page, runbook, design doc, RFC, or Confluence page.

Return a JSON object with a single key "entities" whose value is an array.
Each element must have:
  - "entity_type": one of the values listed above (exact string match)
  - "name": the entity name as it appears in the text
  - "canonical_name": the normalised lowercase form (no extra whitespace)
  - "properties": an object with any additional relevant key-value pairs

Only return entities explicitly mentioned. Do not infer. If no entities are found, return {"entities": []}.
Do NOT wrap the JSON in markdown fences.
"""

ENTITY_EXTRACTION_HUMAN = "Text chunk:\n\n{text}"
```

---

### `EntityExtractor`

```python
# src/knowledge_graph/extraction/extractor.py (continued)
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from uuid     import UUID

import litellm

from src.knowledge_graph.schemas.entity import (
    EntityType, ExtractedEntity, EntityExtractionResult, make_entity_id,
)
from src.knowledge_graph.schemas.events import ChunkIndexedEvent
from src.knowledge_graph.extraction.prompts import (
    ENTITY_EXTRACTION_SYSTEM, ENTITY_EXTRACTION_HUMAN,
)

logger = logging.getLogger(__name__)


class EntityExtractor:
    def __init__(self, settings: ExtractionSettings | None = None) -> None:
        self._settings = settings or ExtractionSettings()

    async def extract(self, event: ChunkIndexedEvent) -> EntityExtractionResult:
        """
        Call the LLM to extract entities from one chunk.

        Raises:
            asyncio.TimeoutError  — if LiteLLM call exceeds timeout_s
            ValueError            — if LLM response cannot be parsed as valid JSON
            pydantic.ValidationError — if a parsed entity fails schema validation
        """
        start = time.monotonic()

        messages = [
            {"role": "system", "content": ENTITY_EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": ENTITY_EXTRACTION_HUMAN.format(text=event.text),
            },
        ]

        response = await asyncio.wait_for(
            litellm.acompletion(
                model       = self._settings.model_id,
                messages    = messages,
                temperature = self._settings.temperature,
                max_tokens  = self._settings.max_tokens,
            ),
            timeout = self._settings.timeout_s,
        )

        raw_content = response.choices[0].message.content or ""
        entities    = self._parse_response(raw_content, event.source_id, event.chunk_id)
        duration_ms = (time.monotonic() - start) * 1000

        logger.debug(
            "EntityExtractor: chunk=%s extracted=%d entities in %.1f ms",
            event.chunk_id, len(entities), duration_ms,
        )

        return EntityExtractionResult(
            chunk_id    = event.chunk_id,
            source_id   = event.source_id,
            entities    = entities,
            duration_ms = duration_ms,
        )

    def _parse_response(
        self,
        raw: str,
        source_id: UUID,
        chunk_id:  UUID,
    ) -> list[ExtractedEntity]:
        """Parse raw LLM JSON into validated ExtractedEntity objects."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned non-JSON content: {raw!r}") from exc

        now      = datetime.now(tz=timezone.utc)
        entities = []
        for item in data.get("entities", []):
            try:
                entity_type    = EntityType(item["entity_type"])
                canonical_name = item.get("canonical_name") or item["name"].strip().lower()
                entity_id      = make_entity_id(entity_type, canonical_name)
                entities.append(
                    ExtractedEntity(
                        entity_id      = entity_id,
                        entity_type    = entity_type,
                        name           = item["name"],
                        canonical_name = canonical_name,
                        source_id      = source_id,
                        chunk_id       = chunk_id,
                        created_at     = now,
                        properties     = item.get("properties", {}),
                    )
                )
            except (KeyError, ValueError) as exc:
                # Log malformed entity item and skip; do not fail the whole chunk.
                logger.warning(
                    "EntityExtractor: skipping malformed entity item %r: %s", item, exc
                )
        return entities
```

**500 ms SLA design (AC-5):**

The 500 ms target is a p50 average. `gpt-4o-mini` at low token count (≤ 512 output tokens) achieves ~300–400 ms p50 latency. The `asyncio.wait_for(timeout=2.0)` hard cap prevents p99 tail latency from blocking the Kafka consumer loop for more than 2 seconds per chunk. The caller (`EntityConsumer`, TASK-US028-04) records `duration_ms` from `EntityExtractionResult` to a Prometheus histogram for SLA tracking.

**Why `JsonOutputParser` is not used here:**

LangChain's `JsonOutputParser` adds a second LLM call on parse failure. For a high-throughput pipeline (1,000 chunks/min), the extra retry latency is unacceptable. Instead, `_parse_response` does a single `json.loads` with graceful per-item error skipping, which keeps the fast path minimal and makes test mocking straightforward.

## Acceptance Criteria

- [ ] `EntityExtractor.extract()` returns `EntityExtractionResult` with `duration_ms > 0`
- [ ] LLM returning `{"entities": []}` produces an empty `EntityExtractionResult.entities` list (no error)
- [ ] A malformed entity item in the LLM response is skipped (logged) — other entities in the same response are still returned
- [ ] LLM call exceeding `timeout_s` raises `asyncio.TimeoutError` (propagated to caller for retry)
- [ ] LLM returning invalid JSON raises `ValueError` (propagated to caller for retry)
- [ ] `entity_id` in each returned `ExtractedEntity` is the deterministic hash of `entity_type + canonical_name`

## Dependencies

- TASK-US028-01 (`EntityType`, `ExtractedEntity`, `EntityExtractionResult`, `make_entity_id`, `ChunkIndexedEvent`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `litellm.acompletion` via `AsyncMock`; no live LLM calls in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
