"""Neo4j entity store for writing extracted entities as typed nodes.

TASK-US028-03: Implements ``Neo4jEntityStore`` which persists ``ExtractedEntity``
objects to Neo4j using ``MERGE`` on ``entity_id``, satisfying AC-3 (required node
properties) and AC-4 (deduplication guarantees).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from neo4j import AsyncDriver, AsyncGraphDatabase
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.knowledge_graph.schemas.entity import ExtractedEntity
from src.knowledge_graph.stores.constraints import CONSTRAINT_STATEMENTS

logger = logging.getLogger(__name__)


class Neo4jSettings(BaseSettings):
    """Settings for the Neo4j connection, sourced from ``NEO4J_*`` env vars."""

    model_config = SettingsConfigDict(env_prefix="NEO4J_", env_file=".env", extra="ignore")

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "password"  # noqa: S105
    database: str = "neo4j"
    # Max entities per UNWIND batch; reduces round-trips for bulk extraction results.
    batch_size: int = 100


class Neo4jEntityStore:
    """Writes ``ExtractedEntity`` objects to Neo4j as typed nodes.

    Uses ``MERGE`` on the uniqueness-constrained ``entity_id`` property so that
    repeated extractions of the same entity produce exactly one node (AC-4).

    Dynamic Cypher labels come exclusively from ``EntityType`` enum values —
    never from user-supplied input — so there is no Cypher-injection risk.
    """

    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self._settings = settings or Neo4jSettings()
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.username, self._settings.password),
        )

    async def apply_constraints(self) -> None:
        """Create uniqueness constraints for all entity type labels (idempotent).

        Uses ``IF NOT EXISTS`` so it is safe to call on every application start.
        Must be called once during lifespan startup before any ``merge_entities``
        invocations.
        """
        async with self._driver.session(database=self._settings.database) as session:
            for stmt in CONSTRAINT_STATEMENTS:
                await session.run(stmt)

    async def merge_entities(self, entities: list[ExtractedEntity]) -> None:
        """Write entities to Neo4j using ``MERGE`` on ``entity_id``.

        Entities are grouped by ``entity_type`` so each ``UNWIND`` targets a
        single node label.  Within each label group, entities are split into
        sub-batches of ``batch_size`` to avoid overly large payloads.

        Cypher pattern per label::

            UNWIND $batch AS props
            MERGE (n:<Label> {entity_id: props.entity_id})
            ON CREATE SET n = props, n.created_at = props.created_at
            ON MATCH  SET n.name      = props.name,
                          n.source_id = props.source_id,
                          n.updated_at = props.updated_at

        Args:
            entities: Entities to persist.  Empty list returns immediately
                      without opening a Neo4j session.
        """
        if not entities:
            return

        now = datetime.now(tz=UTC).isoformat()

        # Group by entity_type so each UNWIND targets a single node label.
        by_type: dict[str, list[dict]] = {}
        for entity in entities:
            props: dict = {
                "entity_id": entity.entity_id,
                "type": entity.entity_type.value,
                "name": entity.name,
                "source_id": str(entity.source_id),
                "created_at": entity.created_at.isoformat(),
                "updated_at": now,
                **entity.properties,
            }
            by_type.setdefault(entity.entity_type.value, []).append(props)

        async with self._driver.session(database=self._settings.database) as session:
            for label, batch in by_type.items():
                for i in range(0, len(batch), self._settings.batch_size):
                    sub = batch[i : i + self._settings.batch_size]
                    await session.run(
                        f"""
                        UNWIND $batch AS props
                        MERGE (n:{label} {{entity_id: props.entity_id}})
                        ON CREATE SET n = props,
                                      n.created_at = props.created_at
                        ON MATCH  SET n.name       = props.name,
                                      n.source_id  = props.source_id,
                                      n.updated_at = props.updated_at
                        """,
                        batch=sub,
                    )

        logger.debug(
            "Neo4jEntityStore: merged %d entities across %d labels",
            len(entities),
            len(by_type),
        )

    async def close(self) -> None:
        """Close the underlying Neo4j driver and release connections."""
        await self._driver.close()
