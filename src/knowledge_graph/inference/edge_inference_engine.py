"""EdgeInferenceEngine — relationship inference from co-located entities.

TASK-US030-02: Implements a two-tier inference pipeline:
  1. Fast heuristic pass: every entity pair in a chunk → REFERENCES edge.
  2. Optional LLM pass: infers typed directional edges (DEPENDS_ON, OWNED_BY,
     HAS_INCIDENT, DEPLOYED_BY). Typed edges supersede the heuristic REFERENCES
     edge for the same pair.

Throughput design:
  Target: 500 chunks in ≤ 5 s (10 ms/chunk on the fast path).
  The heuristic path is O(n²) in entities per chunk (≤ 7 → ≤ 21 pairs, < 1 ms).
  LLM latency is amortised via asyncio.gather concurrency in GraphUpdaterConsumer.
"""
from __future__ import annotations

import asyncio
import json
import logging
from itertools import combinations
from uuid import UUID

import litellm
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.llm.local_ollama_chain import get_ollama_base_url

from src.knowledge_graph.inference.prompts import EDGE_INFERENCE_HUMAN, EDGE_INFERENCE_SYSTEM
from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.schemas.entity import EntityExtractionResult, EntityType, ExtractedEntity
from src.knowledge_graph.schemas.relationship import GraphRelationship

logger = logging.getLogger(__name__)


class EdgeInferenceSettings(BaseSettings):
    """Runtime configuration for EdgeInferenceEngine — env-prefix EDGE_INFERENCE_."""

    model_config = SettingsConfigDict(env_prefix="EDGE_INFERENCE_", env_file=".env", extra="ignore")

    # If False, only the heuristic pass runs (REFERENCES edges). Fast path only.
    # Set True to enable LLM-based directional edge typing.
    use_llm: bool = True
    model_id: str = "ollama/llama3.2"
    temperature: float = 0.0
    max_tokens: int = 512
    # Per-chunk LLM timeout. Must be short to meet the 5 s / 500-chunk budget.
    timeout_s: float = 1.5
    # Minimum confidence to include an LLM-inferred edge.
    min_weight: float = 0.5
    ttl_days: int = 30


class EdgeInferenceEngine:
    """Infers graph relationships for entities co-located within a single chunk."""

    def __init__(self, settings: EdgeInferenceSettings | None = None) -> None:
        self._settings = settings or EdgeInferenceSettings()

    async def infer(
        self,
        result: EntityExtractionResult,
        chunk_text: str,
    ) -> list[GraphRelationship]:
        """Infer relationships for all entity pairs found in a single chunk.

        Fast path  (always runs): every entity pair → REFERENCES edge.
        LLM path   (when use_llm=True): LLM infers typed directional edges;
                   typed edges replace the REFERENCES fallback for the same pair.

        Returns deduplicated list of GraphRelationship objects.
        """
        if len(result.entities) < 2:
            return []

        heuristic_edges = self._heuristic_edges(result.entities, result.chunk_id, result.source_id)
        if not self._settings.use_llm:
            return heuristic_edges

        try:
            llm_edges = await self._llm_edges(
                result.entities, chunk_text, result.chunk_id, result.source_id
            )
        except (TimeoutError, Exception) as exc:
            logger.warning(
                "EdgeInferenceEngine: LLM pass failed chunk=%s: %s — using heuristic only",
                result.chunk_id,
                exc,
            )
            return heuristic_edges

        return self._merge_edges(heuristic_edges, llm_edges)

    # ------------------------------------------------------------------
    # Fast path
    # ------------------------------------------------------------------

    def _heuristic_edges(
        self,
        entities: list[ExtractedEntity],
        chunk_id: UUID,
        source_id: UUID,
    ) -> list[GraphRelationship]:
        """Prefer deterministic typed edges, otherwise fall back to REFERENCES."""
        edges = []
        for a, b in combinations(entities, 2):
            try:
                typed_edges = self._deterministic_edges(
                    a=a,
                    b=b,
                    chunk_id=chunk_id,
                    source_id=source_id,
                )
                if typed_edges:
                    edges.extend(typed_edges)
                    continue

                edges.append(
                    GraphRelationship.create(
                        from_entity_id=a.entity_id,
                        to_entity_id=b.entity_id,
                        edge_type=EdgeType.REFERENCES,
                        source_id=source_id,
                        chunk_id=chunk_id,
                        weight=0.5,
                        ttl_days=self._settings.ttl_days,
                    )
                )
            except ValueError:
                pass  # skip self-loops (guard for safety)
        return edges

    def _deterministic_edges(
        self,
        *,
        a: ExtractedEntity,
        b: ExtractedEntity,
        chunk_id: UUID,
        source_id: UUID,
    ) -> list[GraphRelationship]:
        repo_doc = self._repository_document_edge(a, b, chunk_id, source_id)
        if repo_doc is not None:
            return [repo_doc]

        repo_owner = self._repository_owner_edge(a, b, chunk_id, source_id)
        if repo_owner is not None:
            return [repo_owner]

        service_repo = self._service_repository_edge(a, b, chunk_id, source_id)
        if service_repo is not None:
            return [service_repo]

        return []

    def _repository_document_edge(
        self,
        a: ExtractedEntity,
        b: ExtractedEntity,
        chunk_id: UUID,
        source_id: UUID,
    ) -> GraphRelationship | None:
        repository = self._find_entity_pair(a, b, EntityType.REPOSITORY, EntityType.DOCUMENT)
        if repository is None:
            return None
        repo_entity, doc_entity = repository
        if repo_entity.properties.get("repository") != doc_entity.properties.get("repository"):
            return None
        return GraphRelationship.create(
            from_entity_id=doc_entity.entity_id,
            to_entity_id=repo_entity.entity_id,
            edge_type=EdgeType.REFERENCES,
            source_id=source_id,
            chunk_id=chunk_id,
            weight=0.7,
            ttl_days=self._settings.ttl_days,
        )

    def _repository_owner_edge(
        self,
        a: ExtractedEntity,
        b: ExtractedEntity,
        chunk_id: UUID,
        source_id: UUID,
    ) -> GraphRelationship | None:
        pair = self._find_entity_pair(a, b, EntityType.REPOSITORY, EntityType.DEVELOPER)
        if pair is None:
            return None
        repo_entity, owner_entity = pair
        owner_name = repo_entity.properties.get("owner")
        if not owner_name:
            return None
        if str(owner_name).strip().lower() != owner_entity.canonical_name:
            return None
        return GraphRelationship.create(
            from_entity_id=repo_entity.entity_id,
            to_entity_id=owner_entity.entity_id,
            edge_type=EdgeType.OWNED_BY,
            source_id=source_id,
            chunk_id=chunk_id,
            weight=0.95,
            ttl_days=self._settings.ttl_days,
        )

    def _service_repository_edge(
        self,
        a: ExtractedEntity,
        b: ExtractedEntity,
        chunk_id: UUID,
        source_id: UUID,
    ) -> GraphRelationship | None:
        pair = self._find_entity_pair(a, b, EntityType.SERVICE, EntityType.REPOSITORY)
        if pair is None:
            return None
        service_entity, repo_entity = pair
        if service_entity.properties.get("repository") != repo_entity.properties.get("repository"):
            return None
        return GraphRelationship.create(
            from_entity_id=service_entity.entity_id,
            to_entity_id=repo_entity.entity_id,
            edge_type=EdgeType.DEPENDS_ON,
            source_id=source_id,
            chunk_id=chunk_id,
            weight=0.8,
            ttl_days=self._settings.ttl_days,
        )

    def _find_entity_pair(
        self,
        a: ExtractedEntity,
        b: ExtractedEntity,
        left_type: EntityType,
        right_type: EntityType,
    ) -> tuple[ExtractedEntity, ExtractedEntity] | None:
        if a.entity_type == left_type and b.entity_type == right_type:
            return a, b
        if a.entity_type == right_type and b.entity_type == left_type:
            return b, a
        return None

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    async def _llm_edges(
        self,
        entities: list[ExtractedEntity],
        text: str,
        chunk_id: UUID,
        source_id: UUID,
    ) -> list[GraphRelationship]:
        entity_list = "\n".join(f"- {e.name} ({e.entity_type.value})" for e in entities)
        messages = [
            {"role": "system", "content": EDGE_INFERENCE_SYSTEM},
            {
                "role": "user",
                "content": EDGE_INFERENCE_HUMAN.format(entity_list=entity_list, text=text),
            },
        ]
        response = await asyncio.wait_for(
            litellm.acompletion(
                model=self._settings.model_id,
                api_base=get_ollama_base_url(),
                messages=messages,
                temperature=self._settings.temperature,
                max_tokens=self._settings.max_tokens,
            ),
            timeout=self._settings.timeout_s,
        )
        raw = response.choices[0].message.content or ""
        data = json.loads(raw)

        name_map: dict[str, str] = {e.name.strip().lower(): e.entity_id for e in entities}

        edges = []
        for item in data.get("relationships", []):
            try:
                from_id = name_map.get(item["from"].strip().lower())
                to_id = name_map.get(item["to"].strip().lower())
                weight = float(item.get("weight", 1.0))
                if not from_id or not to_id:
                    continue
                if weight < self._settings.min_weight:
                    continue
                edge_type = EdgeType(item["type"])
                edges.append(
                    GraphRelationship.create(
                        from_entity_id=from_id,
                        to_entity_id=to_id,
                        edge_type=edge_type,
                        source_id=source_id,
                        chunk_id=chunk_id,
                        weight=weight,
                        ttl_days=self._settings.ttl_days,
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.debug(
                    "EdgeInferenceEngine: skipping malformed edge item %r: %s", item, exc
                )
        return edges

    # ------------------------------------------------------------------
    # Merge: LLM-typed edges win over REFERENCES for the same pair
    # ------------------------------------------------------------------

    def _merge_edges(
        self,
        heuristic: list[GraphRelationship],
        llm: list[GraphRelationship],
    ) -> list[GraphRelationship]:
        """Drop heuristic REFERENCES edges for any pair already covered by an LLM edge."""
        llm_pairs: set[tuple[str, str]] = {(e.from_entity_id, e.to_entity_id) for e in llm}
        filtered_heuristic = [
            e for e in heuristic if (e.from_entity_id, e.to_entity_id) not in llm_pairs
        ]
        return filtered_heuristic + llm
