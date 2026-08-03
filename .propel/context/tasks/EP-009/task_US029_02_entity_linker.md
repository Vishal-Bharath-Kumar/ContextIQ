# TASK-US029-02 — `EntityLinker`: Extract Seed Entity IDs from Ranked Context

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US029-02 |
| User Story | US-029 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `EntityLinker` — the component that scans `ranked_context` items for embedded entity references and returns a deduplicated list of seed `entity_id` strings for the graph traversal. Explicit entity IDs (stored in context item metadata by the indexing pipeline) are extracted first. If none are found, a lightweight LiteLLM call resolves entity names to graph IDs via a `GraphTraversalClient` lookup. Satisfies AC-1 (traversal starting from entities identified in ranked context).

## Implementation Details

**Technology:** Python 3.11+, LiteLLM `>=1.30`, Pydantic v2

**File locations:**
- `src/knowledge_graph/traversal/entity_linker.py` — `EntityLinker`, `EntityLinkerSettings`
- `tests/knowledge_graph/test_entity_linker.py`

---

### `RankedContextItem` contract

`EntityLinker` consumes the `ranked_context` list from `AgentState`. Each item is a dict (or Pydantic model) with at least:

```python
{
    "text":      str,
    "score":     float,
    "source_id": str,        # UUID of the knowledge source
    "metadata":  {
        # Optionally present if the indexing pipeline stored entity IDs:
        "entity_ids": list[str],   # e.g. ["a3f1c2b4d5e6f708", ...]
    }
}
```

If `metadata.entity_ids` is present and non-empty, those IDs are used directly as seeds. This is the fast path — zero LLM calls.

---

### `EntityLinkerSettings`

```python
# src/knowledge_graph/traversal/entity_linker.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class EntityLinkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENTITY_LINKER_", env_file=".env")

    # Fallback LLM for entity name extraction when metadata.entity_ids is absent.
    model_id:          str   = "gpt-4o-mini"
    temperature:       float = 0.0
    max_tokens:        int   = 256
    timeout_s:         float = 1.0
    # Maximum seeds forwarded to the traversal; limits fanout.
    max_seeds:         int   = 10
```

---

### `EntityLinker`

```python
# src/knowledge_graph/traversal/entity_linker.py (continued)
import asyncio
import json
import logging
from typing import TYPE_CHECKING

import litellm

if TYPE_CHECKING:
    from src.knowledge_graph.traversal.neo4j_traversal_client import GraphTraversalClient

logger = logging.getLogger(__name__)

_ENTITY_NAME_EXTRACTION_SYSTEM = """\
Extract the names of any software entities (services, repositories, developers, incidents,
deployments, alert rules, or documents) explicitly mentioned in the text.
Return JSON: {"entity_names": ["name1", "name2"]}.
If none, return {"entity_names": []}.
Do NOT wrap in markdown fences.
"""


class EntityLinker:
    def __init__(
        self,
        traversal_client: "GraphTraversalClient",
        settings: EntityLinkerSettings | None = None,
    ) -> None:
        self._client   = traversal_client
        self._settings = settings or EntityLinkerSettings()

    async def resolve(self, ranked_context: list[dict]) -> list[str]:
        """
        Return a deduplicated list of seed entity_ids (up to max_seeds) derived
        from the ranked_context items.

        Fast path  — metadata.entity_ids present in any context item.
        Slow path  — LLM extracts entity names → Neo4j lookup resolves to entity_ids.
        """
        # --- Fast path ---
        explicit_ids: list[str] = []
        for item in ranked_context:
            ids = (item.get("metadata") or {}).get("entity_ids", [])
            explicit_ids.extend(ids)
        explicit_ids = list(dict.fromkeys(explicit_ids))   # deduplicate, preserve order

        if explicit_ids:
            return explicit_ids[: self._settings.max_seeds]

        # --- Slow path: LLM name extraction → graph ID lookup ---
        combined_text = "\n".join(
            item.get("text", "") for item in ranked_context[:5]   # top-5 items only
        )
        names = await self._extract_entity_names(combined_text)
        if not names:
            logger.debug("EntityLinker: no entity names found in ranked_context")
            return []

        entity_ids = await self._client.lookup_entity_ids(names)
        return entity_ids[: self._settings.max_seeds]

    async def _extract_entity_names(self, text: str) -> list[str]:
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model       = self._settings.model_id,
                    messages    = [
                        {"role": "system", "content": _ENTITY_NAME_EXTRACTION_SYSTEM},
                        {"role": "user",   "content": text},
                    ],
                    temperature = self._settings.temperature,
                    max_tokens  = self._settings.max_tokens,
                ),
                timeout = self._settings.timeout_s,
            )
            raw  = response.choices[0].message.content or ""
            data = json.loads(raw)
            return [str(n) for n in data.get("entity_names", [])]
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as exc:
            # Slow-path failure is non-fatal: the traversal runs with zero seeds
            # and the node gracefully skips graph expansion.
            logger.warning("EntityLinker: slow-path name extraction failed: %s", exc)
            return []
```

**Design rationale:**

The fast path covers the steady-state case: once the indexing pipeline stores `entity_ids` in chunk metadata (TASK-US027-01, `ChunkPayload.metadata`), no LLM call is needed for seed resolution. The slow path exists only as a fallback for legacy context items or connectors that do not emit `entity_ids`. The 1-second `timeout_s` for the slow-path call is intentionally tight — the overall 500 ms traversal budget (AC-5) is for the Neo4j query itself; the linker has its own timeout before the traversal begins.

**`metadata.entity_ids` population (upstream dependency):**

`IndexingPipeline.run_for_source()` (TASK-US027-04) stores entity IDs in chunk metadata after entity extraction (TASK-US028) completes. The `ChunkIndexedEvent.metadata` dict therefore carries `entity_ids` in the steady state. This task documents that contract but does not implement the upstream write — that is owned by TASK-US028-04.

## Acceptance Criteria

- [ ] Fast path: if any `ranked_context` item has `metadata.entity_ids`, those IDs are returned without an LLM call
- [ ] Fast path: duplicates across multiple context items are deduplicated in insertion order
- [ ] Fast path: result is capped at `max_seeds` (default 10)
- [ ] Slow path: LLM `asyncio.TimeoutError` is caught and logged; `resolve()` returns `[]` without raising
- [ ] Slow path: LLM JSON parse failure is caught and logged; `resolve()` returns `[]` without raising
- [ ] `mypy --strict` passes

## Dependencies

- TASK-US029-01 (`TraversalConfig`, `GraphContextItem`)
- TASK-US029-03 (`GraphTraversalClient.lookup_entity_ids()` — forward reference resolved at runtime)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `litellm.acompletion` and `GraphTraversalClient.lookup_entity_ids` via `AsyncMock`; no live calls in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
