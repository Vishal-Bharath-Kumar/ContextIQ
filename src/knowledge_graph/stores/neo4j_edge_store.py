"""Neo4j edge store for writing graph relationships — TASK-US030-03.

Implements ``Neo4jEdgeStore`` which persists ``GraphRelationship`` objects to
Neo4j using ``MERGE`` on ``(from_entity_id, to_entity_id, edge_type)``.

Satisfies:
  AC-2  ``merge_relationships()`` — MERGE on triple key; ON MATCH updates TTL.
  AC-3  ``delete_entity_relationships()`` — tombstone deletes all incident edges.
  AC-5  ``expire_stale_relationships()`` — batched TTL expiry loop.
"""
from __future__ import annotations

import logging
from datetime import datetime

from neo4j import AsyncDriver, AsyncGraphDatabase

from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.schemas.relationship import GraphRelationship
from src.knowledge_graph.stores.neo4j_store import Neo4jSettings

logger = logging.getLogger(__name__)

# Closed mapping from EdgeType enum to Cypher relationship-type string.
# Never derived from user input — safe for dynamic label interpolation.
_EDGE_CYPHER: dict[EdgeType, str] = {
    EdgeType.DEPENDS_ON: "DEPENDS_ON",
    EdgeType.OWNED_BY: "OWNED_BY",
    EdgeType.HAS_INCIDENT: "HAS_INCIDENT",
    EdgeType.DEPLOYED_BY: "DEPLOYED_BY",
    EdgeType.REFERENCES: "REFERENCES",
}

_EXPIRE_BATCH_SIZE = 10_000


class Neo4jEdgeStore:
    """Writes ``GraphRelationship`` objects to Neo4j as typed directed edges.

    Uses ``MERGE`` on the uniqueness triple ``(from_entity_id, to_entity_id,
    edge_type)`` so repeated extraction of the same relationship updates TTL
    metadata without creating duplicate edges (AC-2).

    Dynamic Cypher relationship-type labels come exclusively from
    ``_EDGE_CYPHER[rel.edge_type]``, which is keyed by the bounded ``EdgeType``
    enum — never from user-supplied input — so there is no Cypher-injection
    risk.
    """

    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self._settings = settings or Neo4jSettings()
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.username, self._settings.password),
        )

    async def merge_relationships(self, relationships: list[GraphRelationship]) -> int:
        """Upsert all relationships into Neo4j using MERGE.

        MERGE key: ``(from_entity_id, to_entity_id, edge_type)``.

        For each ``EdgeType`` present in the batch, one ``UNWIND`` query is
        executed per sub-batch to minimise round-trips.

        ON CREATE: sets all properties including ``created_at``.
        ON MATCH : updates ``weight``, ``updated_at``, ``ttl_expires_at``,
                   ``chunk_id``, ``source_id``.  Does NOT overwrite ``created_at``.

        Args:
            relationships: Relationships to persist.  Empty list returns
                           immediately without opening a Neo4j session.

        Returns:
            Number of relationships processed (equals ``len(relationships)``).
        """
        if not relationships:
            return 0

        # Group by Cypher label so each UNWIND targets a single relationship type.
        by_type: dict[str, list[dict]] = {}
        for rel in relationships:
            label = _EDGE_CYPHER[rel.edge_type]
            props: dict = {
                "from_id": rel.from_entity_id,
                "to_id": rel.to_entity_id,
                "source_id": str(rel.source_id),
                "chunk_id": str(rel.chunk_id),
                "weight": rel.weight,
                "created_at": rel.created_at.isoformat(),
                "updated_at": rel.updated_at.isoformat(),
                "ttl_expires_at": rel.ttl_expires_at.isoformat(),
            }
            by_type.setdefault(label, []).append(props)

        async with self._driver.session(database=self._settings.database) as session:
            for label, batch in by_type.items():
                for i in range(0, len(batch), self._settings.batch_size):
                    sub = batch[i : i + self._settings.batch_size]
                    await session.run(
                        f"""
                        UNWIND $batch AS props
                        MATCH (a {{entity_id: props.from_id}})
                        MATCH (b {{entity_id: props.to_id}})
                        MERGE (a)-[r:{label}]->(b)
                        ON CREATE SET
                            r.source_id      = props.source_id,
                            r.chunk_id       = props.chunk_id,
                            r.weight         = props.weight,
                            r.created_at     = props.created_at,
                            r.updated_at     = props.updated_at,
                            r.ttl_expires_at = props.ttl_expires_at
                        ON MATCH SET
                            r.source_id      = props.source_id,
                            r.chunk_id       = props.chunk_id,
                            r.weight         = props.weight,
                            r.updated_at     = props.updated_at,
                            r.ttl_expires_at = props.ttl_expires_at
                        """,
                        batch=sub,
                    )

        logger.debug(
            "Neo4jEdgeStore: merged %d relationships across %d edge types",
            len(relationships),
            len(by_type),
        )
        return len(relationships)

    async def delete_entity_relationships(self, entity_id: str) -> int:
        """Tombstone pattern (AC-3): delete all relationships incident on the entity.

        Removes both incoming and outgoing relationships when the entity is
        removed from the source system.

        Args:
            entity_id: The ``entity_id`` property value of the node whose
                       relationships should be deleted.

        Returns:
            Number of relationships deleted.
        """
        result = await self._run_write(
            """
            MATCH (n {entity_id: $entity_id})-[r]-()
            WITH r, count(r) AS total
            DELETE r
            RETURN total
            """,
            entity_id=entity_id,
        )
        count: int = result[0]["total"] if result else 0
        logger.info(
            "Neo4jEdgeStore: tombstone deleted %d relationships for entity=%s",
            count,
            entity_id,
        )
        return count

    async def expire_stale_relationships(self, cutoff: datetime) -> int:
        """AC-5: remove relationships whose ``ttl_expires_at`` precedes ``cutoff``.

        Runs in batches of 10 000 to avoid long-running transactions on large
        graphs.  Loops until a batch returns fewer than 10 000 deletions,
        signalling no more stale relationships remain.

        Args:
            cutoff: Relationships with ``ttl_expires_at < cutoff`` are deleted.

        Returns:
            Total number of expired relationships deleted.
        """
        total_deleted = 0

        while True:
            result = await self._run_write(
                """
                MATCH ()-[r]->()
                WHERE r.ttl_expires_at < $cutoff
                WITH r LIMIT $batch_size
                DELETE r
                RETURN count(r) AS deleted
                """,
                cutoff=cutoff.isoformat(),
                batch_size=_EXPIRE_BATCH_SIZE,
            )
            deleted: int = result[0]["deleted"] if result else 0
            total_deleted += deleted
            if deleted < _EXPIRE_BATCH_SIZE:
                break  # no more stale relationships

        if total_deleted:
            logger.info(
                "Neo4jEdgeStore: expired %d stale relationships (cutoff=%s)",
                total_deleted,
                cutoff.isoformat(),
            )
        return total_deleted

    async def close(self) -> None:
        """Close the underlying Neo4j driver."""
        await self._driver.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _run_write(self, query: str, **params: object) -> list[dict]:
        async with self._driver.session(database=self._settings.database) as session:
            result = await session.run(query.strip(), **params)
            return [dict(record) async for record in result]
