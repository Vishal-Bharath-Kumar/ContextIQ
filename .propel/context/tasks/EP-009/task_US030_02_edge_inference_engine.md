# TASK-US030-02 — `EdgeInferenceEngine`: Relationship Inference from Co-Located Entities

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US030-02 |
| User Story | US-030 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `EdgeInferenceEngine` — the component that accepts an `EntityExtractionResult` (a list of entities from one chunk) and returns a list of `GraphRelationship` objects. Uses a two-tier approach: a fast heuristic pass (co-location → `REFERENCES`) followed by an optional LLM pass that infers directional typed edges (`DEPENDS_ON`, `OWNED_BY`, `HAS_INCIDENT`, `DEPLOYED_BY`). Satisfies AC-2 (new relationships inferred from changed chunks) and the throughput leg of AC-4 (5 s / 500 chunks = ≤ 10 ms per chunk on the fast path).

## Implementation Details

**Technology:** Python 3.11+, LiteLLM `>=1.30`, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/knowledge_graph/inference/edge_inference_engine.py` — `EdgeInferenceEngine`, `EdgeInferenceSettings`
- `src/knowledge_graph/inference/prompts.py` — `EDGE_INFERENCE_SYSTEM`
- `tests/knowledge_graph/test_edge_inference_engine.py`

---

### `EdgeInferenceSettings`

```python
# src/knowledge_graph/inference/edge_inference_engine.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class EdgeInferenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDGE_INFERENCE_", env_file=".env")

    # If False, only the heuristic pass runs (REFERENCES edges). Fast path only.
    # Set True to enable LLM-based directional edge typing.
    use_llm:     bool  = True
    model_id:    str   = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens:  int   = 512
    # Per-chunk LLM timeout. Must be short to meet the 5 s / 500-chunk budget.
    timeout_s:   float = 1.5
    # Minimum confidence to include an LLM-inferred edge.
    min_weight:  float = 0.5
    ttl_days:    int   = 30
```

---

### Edge inference prompt

```python
# src/knowledge_graph/inference/prompts.py
EDGE_INFERENCE_SYSTEM = """\
You are an expert at identifying relationships between software engineering entities.
Given a list of entities extracted from a text chunk, infer directed relationships between them.

Allowed relationship types (exact strings only):
- DEPENDS_ON  : entity A relies on entity B to function
- OWNED_BY    : entity A is owned or maintained by entity B (a Developer or team)
- HAS_INCIDENT: entity A experienced incident B
- DEPLOYED_BY : entity A was deployed by entity B (a Deployment or CI/CD system)
- REFERENCES  : entity A mentions or references entity B (catch-all)

Return JSON: {"relationships": [{"from": "<name>", "to": "<name>", "type": "<TYPE>", "weight": 0.9}]}.
Only return relationships explicitly supported by the text. Do NOT infer speculative links.
If no directional relationships can be determined, return {"relationships": []}.
Do NOT wrap the JSON in markdown fences.
"""

EDGE_INFERENCE_HUMAN = """\
Entities found in this chunk:
{entity_list}

Chunk text:
{text}
"""
```

---

### `EdgeInferenceEngine`

```python
# src/knowledge_graph/inference/edge_inference_engine.py (continued)
import asyncio
import json
import logging
from itertools  import combinations
from uuid       import UUID

import litellm

from src.knowledge_graph.schemas.entity       import ExtractedEntity, EntityExtractionResult
from src.knowledge_graph.schemas.edge         import EdgeType
from src.knowledge_graph.schemas.relationship import GraphRelationship
from src.knowledge_graph.inference.prompts    import EDGE_INFERENCE_SYSTEM, EDGE_INFERENCE_HUMAN

logger = logging.getLogger(__name__)


class EdgeInferenceEngine:
    def __init__(self, settings: EdgeInferenceSettings | None = None) -> None:
        self._settings = settings or EdgeInferenceSettings()

    async def infer(
        self,
        result:     EntityExtractionResult,
        chunk_text: str,
    ) -> list[GraphRelationship]:
        """
        Infer relationships for all entity pairs found in a single chunk.

        Fast path  (always runs): every entity pair → REFERENCES edge.
        LLM path   (when use_llm=True): LLM infers typed directional edges;
                   typed edges replace the REFERENCES fallback for the same pair.

        Returns deduplicated list of GraphRelationship objects.
        """
        if len(result.entities) < 2:
            return []

        # --- Fast path: co-location REFERENCES edges ---
        heuristic_edges = self._heuristic_edges(result.entities, result.chunk_id, result.source_id)
        if not self._settings.use_llm or len(result.entities) < 2:
            return heuristic_edges

        # --- LLM path: typed directional edges ---
        try:
            llm_edges = await self._llm_edges(result.entities, chunk_text,
                                               result.chunk_id, result.source_id)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "EdgeInferenceEngine: LLM pass failed chunk=%s: %s — using heuristic only",
                result.chunk_id, exc,
            )
            return heuristic_edges

        return self._merge_edges(heuristic_edges, llm_edges)

    # ------------------------------------------------------------------ #
    # Fast path                                                            #
    # ------------------------------------------------------------------ #

    def _heuristic_edges(
        self,
        entities:  list[ExtractedEntity],
        chunk_id:  UUID,
        source_id: UUID,
    ) -> list[GraphRelationship]:
        """All unique ordered pairs → REFERENCES edge (co-location signal)."""
        edges = []
        for a, b in combinations(entities, 2):
            try:
                edges.append(
                    GraphRelationship.create(
                        from_entity_id = a.entity_id,
                        to_entity_id   = b.entity_id,
                        edge_type      = EdgeType.REFERENCES,
                        source_id      = source_id,
                        chunk_id       = chunk_id,
                        weight         = 0.5,         # co-location is a weak signal
                        ttl_days       = self._settings.ttl_days,
                    )
                )
            except ValueError:
                pass   # skip self-loops (shouldn't occur; guard for safety)
        return edges

    # ------------------------------------------------------------------ #
    # LLM path                                                             #
    # ------------------------------------------------------------------ #

    async def _llm_edges(
        self,
        entities:  list[ExtractedEntity],
        text:      str,
        chunk_id:  UUID,
        source_id: UUID,
    ) -> list[GraphRelationship]:
        entity_list = "\n".join(
            f"- {e.name} ({e.entity_type.value})" for e in entities
        )
        messages = [
            {"role": "system", "content": EDGE_INFERENCE_SYSTEM},
            {"role": "user",   "content": EDGE_INFERENCE_HUMAN.format(
                entity_list=entity_list, text=text
            )},
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
        raw  = response.choices[0].message.content or ""
        data = json.loads(raw)

        # Build a name → entity_id lookup for the entities in this chunk.
        name_map: dict[str, str] = {
            e.name.strip().lower(): e.entity_id for e in entities
        }

        edges = []
        for item in data.get("relationships", []):
            try:
                from_id = name_map.get(item["from"].strip().lower())
                to_id   = name_map.get(item["to"].strip().lower())
                weight  = float(item.get("weight", 1.0))
                if not from_id or not to_id:
                    continue
                if weight < self._settings.min_weight:
                    continue
                edge_type = EdgeType(item["type"])
                edges.append(
                    GraphRelationship.create(
                        from_entity_id = from_id,
                        to_entity_id   = to_id,
                        edge_type      = edge_type,
                        source_id      = source_id,
                        chunk_id       = chunk_id,
                        weight         = weight,
                        ttl_days       = self._settings.ttl_days,
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.debug("EdgeInferenceEngine: skipping malformed edge item %r: %s", item, exc)
        return edges

    # ------------------------------------------------------------------ #
    # Merge: LLM-typed edges win over REFERENCES for the same pair        #
    # ------------------------------------------------------------------ #

    def _merge_edges(
        self,
        heuristic: list[GraphRelationship],
        llm:       list[GraphRelationship],
    ) -> list[GraphRelationship]:
        """
        For any (from_id, to_id) pair where the LLM returned a typed edge,
        drop the heuristic REFERENCES edge for that pair.
        LLM-inferred typed edges carry higher signal quality.
        """
        llm_pairs: set[tuple[str, str]] = {
            (e.from_entity_id, e.to_entity_id) for e in llm
        }
        filtered_heuristic = [
            e for e in heuristic
            if (e.from_entity_id, e.to_entity_id) not in llm_pairs
        ]
        return filtered_heuristic + llm
```

**Throughput design (AC-4):**

Target: 500 chunks in ≤ 5 s = 10 ms/chunk. The fast path (`_heuristic_edges`) is O(n²) in the number of entities per chunk, which is typically ≤ 7 entity types per chunk → at most 21 pairs → pure Python computation in < 1 ms. When `use_llm=True`, the LLM call adds latency. `GraphUpdaterConsumer` (TASK-US030-04) processes chunks concurrently with `asyncio.gather` (bounded by a semaphore), so LLM latency is amortised across the batch. At `timeout_s=1.5` and concurrency=4, effective throughput is `4 × 1 / 1.5 ≈ 2.7 chunks/s` on the LLM path — setting `use_llm=False` or reducing model calls for large batches is the recommended tuning knob.

## Acceptance Criteria

- [ ] `infer()` with a single entity returns `[]` (no pair = no edge)
- [ ] `infer()` with two entities and `use_llm=False` returns exactly one `REFERENCES` edge
- [ ] `infer()` with three entities and `use_llm=False` returns exactly three `REFERENCES` edges (all combinations)
- [ ] LLM-typed edge for pair (A→B) suppresses the heuristic `REFERENCES` edge for the same pair
- [ ] LLM `asyncio.TimeoutError` falls back to heuristic edges (no exception propagated to caller)
- [ ] LLM returning an entity name not in the chunk is silently skipped
- [ ] `weight < min_weight` edges from LLM are filtered out

## Dependencies

- TASK-US030-01 (`GraphRelationship`, `RelationshipExpirySettings`)
- TASK-US028-01 (`ExtractedEntity`, `EntityExtractionResult`, `EdgeType`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `litellm.acompletion` via `AsyncMock`; no live LLM calls in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
