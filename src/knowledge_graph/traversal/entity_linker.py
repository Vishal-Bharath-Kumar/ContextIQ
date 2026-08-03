"""EntityLinker: resolves seed entity IDs from ranked context — TASK-US029-02."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import litellm
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.llm.local_ollama_chain import get_ollama_base_url

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


class EntityLinkerSettings(BaseSettings):
    """Env-configurable settings for EntityLinker — TASK-US029-02."""

    model_config = SettingsConfigDict(env_prefix="ENTITY_LINKER_", env_file=".env", extra="ignore")

    # Fallback LLM for entity name extraction when metadata.entity_ids is absent.
    model_id: str = "ollama/llama3.2"
    temperature: float = 0.0
    max_tokens: int = 256
    timeout_s: float = 1.0
    # Maximum seeds forwarded to the traversal; limits fanout.
    max_seeds: int = 10


class EntityLinker:
    """Extracts seed entity IDs from ranked context items.

    Fast path  — reads ``metadata.entity_ids`` stored by the indexing pipeline.
    Slow path  — LLM extracts entity names; ``GraphTraversalClient`` resolves IDs.
    """

    def __init__(
        self,
        traversal_client: GraphTraversalClient,
        settings: EntityLinkerSettings | None = None,
    ) -> None:
        self._client = traversal_client
        self._settings = settings or EntityLinkerSettings()

    async def resolve(self, ranked_context: list[dict[str, object]]) -> list[str]:
        """Return a deduplicated list of seed entity_ids (up to max_seeds).

        Args:
            ranked_context: List of ranked context dicts from ``AgentState``.

        Returns:
            Deduplicated entity ID strings, capped at ``max_seeds``.
        """
        # --- Fast path ---
        explicit_ids: list[str] = []
        for item in ranked_context:
            raw_meta = item.get("metadata")
            metadata: dict[str, object] = raw_meta if isinstance(raw_meta, dict) else {}
            raw_ids = metadata.get("entity_ids", [])
            ids: list[str] = raw_ids if isinstance(raw_ids, list) else []
            explicit_ids.extend(str(eid) for eid in ids)
        explicit_ids = list(dict.fromkeys(explicit_ids))  # deduplicate, preserve order

        if explicit_ids:
            return explicit_ids[: self._settings.max_seeds]

        # --- Slow path: LLM name extraction → graph ID lookup ---
        combined_text = "\n".join(
            str(item.get("content") or item.get("text") or item.get("path_summary") or "")
            for item in ranked_context[:5]
        )
        names = await self._extract_entity_names(combined_text)
        if not names:
            logger.debug("EntityLinker: no entity names found in ranked_context")
            return []

        entity_ids: list[str] = await self._client.lookup_entity_ids(names)
        return entity_ids[: self._settings.max_seeds]

    async def _extract_entity_names(self, text: str) -> list[str]:
        """Call the LLM to extract entity names from ``text``.

        Returns an empty list on timeout or JSON parse failure (non-fatal).
        """
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=self._settings.model_id,
                    api_base=get_ollama_base_url(),
                    messages=[
                        {"role": "system", "content": _ENTITY_NAME_EXTRACTION_SYSTEM},
                        {"role": "user", "content": text},
                    ],
                    temperature=self._settings.temperature,
                    max_tokens=self._settings.max_tokens,
                ),
                timeout=self._settings.timeout_s,
            )
            raw: str = response.choices[0].message.content or ""
            data: dict[str, object] = json.loads(raw)
            names = data.get("entity_names", [])
            if not isinstance(names, list):
                return []
            return [str(n) for n in names]
        except (TimeoutError, json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            # Slow-path failure is non-fatal: the traversal runs with zero seeds
            # and the node gracefully skips graph expansion.
            logger.warning("EntityLinker: slow-path name extraction failed: %s", exc)
            return []
