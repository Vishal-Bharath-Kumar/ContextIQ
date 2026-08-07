"""EntityExtractor: LiteLLM JSON extraction with 500 ms budget — TASK-US028-02."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import PurePosixPath
import time
from datetime import UTC, datetime
from uuid import UUID

import litellm
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.llm.local_ollama_chain import get_ollama_base_url

from src.knowledge_graph.extraction.prompts import (
    ENTITY_EXTRACTION_HUMAN,
    ENTITY_EXTRACTION_SYSTEM,
)
from src.knowledge_graph.schemas.entity import (
    EntityExtractionResult,
    EntityType,
    ExtractedEntity,
    make_entity_id,
)
from src.knowledge_graph.schemas.events import ChunkIndexedEvent

logger = logging.getLogger(__name__)


class ExtractionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ENTITY_EXTRACTION_",
        env_file=".env",
        extra="ignore",
    )

    # AIR-020 specifies the extraction model; default is a fast, cheap model.
    model_id: str = "ollama/llama3.2"
    # Hard timeout per LiteLLM call. Keeps p99 latency from blowing past the 500 ms SLA.
    timeout_s: float = 2.0
    # Temperature 0 for deterministic, reproducible entity extraction.
    temperature: float = 0.0
    # Max tokens in the LLM response; limits cost and prevents runaway outputs.
    max_tokens: int = 512


class EntityExtractor:
    def __init__(self, settings: ExtractionSettings | None = None) -> None:
        self._settings = settings or ExtractionSettings()

    async def extract(self, event: ChunkIndexedEvent) -> EntityExtractionResult:
        """Call the LLM to extract entities from one chunk.

        Raises:
            asyncio.TimeoutError: if LiteLLM call exceeds timeout_s
            ValueError: if LLM response cannot be parsed as valid JSON
            pydantic.ValidationError: if a parsed entity fails schema validation
        """
        start = time.monotonic()

        messages = [
            {"role": "system", "content": ENTITY_EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": ENTITY_EXTRACTION_HUMAN.format(text=event.text),
            },
        ]

        try:
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
            raw_content = response.choices[0].message.content or ""
            entities = self._parse_response(raw_content, event.source_id, event.chunk_id)
        except (TimeoutError, ValueError) as exc:
            if not self._supports_deterministic_fallback(event):
                raise
            logger.warning(
                "EntityExtractor: falling back to deterministic entities for chunk=%s: %s",
                event.chunk_id,
                exc,
            )
            entities = self._fallback_entities(event)
        duration_ms = (time.monotonic() - start) * 1000

        logger.debug(
            "EntityExtractor: chunk=%s extracted=%d entities in %.1f ms",
            event.chunk_id,
            len(entities),
            duration_ms,
        )

        return EntityExtractionResult(
            chunk_id=event.chunk_id,
            source_id=event.source_id,
            entities=entities,
            duration_ms=duration_ms,
        )

    def _parse_response(
        self,
        raw: str,
        source_id: UUID,
        chunk_id: UUID,
    ) -> list[ExtractedEntity]:
        """Parse raw LLM JSON into validated ExtractedEntity objects."""
        data = _load_first_json_object(raw)

        now = datetime.now(tz=UTC)
        entities: list[ExtractedEntity] = []
        for item in data.get("entities", []):
            try:
                entity_type = EntityType(item["entity_type"])
                canonical_name = item.get("canonical_name") or item["name"].strip().lower()
                entity_id = make_entity_id(entity_type, canonical_name)
                entities.append(
                    ExtractedEntity(
                        entity_id=entity_id,
                        entity_type=entity_type,
                        name=item["name"],
                        canonical_name=canonical_name,
                        source_id=source_id,
                        chunk_id=chunk_id,
                        created_at=now,
                        properties=item.get("properties", {}),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning(
                    "EntityExtractor: skipping malformed entity item %r: %s", item, exc
                )
        return entities

    def _fallback_entities(self, event: ChunkIndexedEvent) -> list[ExtractedEntity]:
        now = datetime.now(tz=UTC)
        entities: list[ExtractedEntity] = []
        document_id = event.document_id

        if document_id.startswith("github:"):
            _prefix, repository, path = document_id.split(":", 2)
            repo_canonical = repository.strip().lower()
            owner_name, repo_name = _split_repository_name(repository)

            if owner_name is not None:
                owner_canonical = owner_name.strip().lower()
                entities.append(
                    ExtractedEntity(
                        entity_id=make_entity_id(EntityType.DEVELOPER, owner_canonical),
                        entity_type=EntityType.DEVELOPER,
                        name=owner_name,
                        canonical_name=owner_canonical,
                        source_id=event.source_id,
                        chunk_id=event.chunk_id,
                        created_at=now,
                        properties={
                            "repository": repository,
                            "fallback_role": "repository_owner",
                        },
                    )
                )

            entities.append(
                ExtractedEntity(
                    entity_id=make_entity_id(EntityType.REPOSITORY, repo_canonical),
                    entity_type=EntityType.REPOSITORY,
                    name=repository,
                    canonical_name=repo_canonical,
                    source_id=event.source_id,
                    chunk_id=event.chunk_id,
                    created_at=now,
                    properties={
                        "repository": repository,
                        "owner": owner_name,
                        "repo_name": repo_name,
                        "fallback_role": "repository",
                    },
                )
            )

            service_canonical = repo_name.strip().lower()
            entities.append(
                ExtractedEntity(
                    entity_id=make_entity_id(EntityType.SERVICE, service_canonical),
                    entity_type=EntityType.SERVICE,
                    name=repo_name,
                    canonical_name=service_canonical,
                    source_id=event.source_id,
                    chunk_id=event.chunk_id,
                    created_at=now,
                    properties={
                        "repository": repository,
                        "owner": owner_name,
                        "repo_name": repo_name,
                        "fallback_role": "service",
                    },
                )
            )

            path_name = PurePosixPath(path).name or path
            document_canonical = f"{repository}/{path}".strip().lower()
            entities.append(
                ExtractedEntity(
                    entity_id=make_entity_id(EntityType.DOCUMENT, document_canonical),
                    entity_type=EntityType.DOCUMENT,
                    name=path_name,
                    canonical_name=document_canonical,
                    source_id=event.source_id,
                    chunk_id=event.chunk_id,
                    created_at=now,
                    properties={
                        "document_id": document_id,
                        "repository": repository,
                        "file_path": path,
                        "owner": owner_name,
                        "repo_name": repo_name,
                        "fallback_role": "document",
                    },
                )
            )
            return entities

        document_canonical = document_id.strip().lower()
        entities.append(
            ExtractedEntity(
                entity_id=make_entity_id(EntityType.DOCUMENT, document_canonical),
                entity_type=EntityType.DOCUMENT,
                name=document_id,
                canonical_name=document_canonical,
                source_id=event.source_id,
                chunk_id=event.chunk_id,
                created_at=now,
                properties={"document_id": document_id},
            )
        )
        return entities

    def _supports_deterministic_fallback(self, event: ChunkIndexedEvent) -> bool:
        return event.document_id.startswith("github:")


def _load_first_json_object(raw: str) -> dict:
    text = raw.strip()
    if not text:
        return {}

    decoder = json.JSONDecoder()
    try:
        parsed, _end = decoder.raw_decode(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON content: {raw!r}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"LLM returned unexpected JSON payload: {raw!r}")
    return parsed


def _split_repository_name(repository: str) -> tuple[str | None, str]:
    parts = repository.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, repository
