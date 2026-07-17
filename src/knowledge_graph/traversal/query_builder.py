"""Cypher query builder for Knowledge Graph traversal — TASK-US029-01.

Produces safe, parameterised Cypher for variable-depth multi-edge traversal.
All external inputs (seed IDs, edge type strings) are passed as Cypher
parameters — never interpolated into the query string — preventing injection.
"""
from __future__ import annotations

from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.traversal.schemas import TraversalConfig

# Map EdgeType to the Cypher relationship type string used in the graph.
_EDGE_CYPHER: dict[EdgeType, str] = {
    EdgeType.DEPENDS_ON: "DEPENDS_ON",
    EdgeType.OWNED_BY: "OWNED_BY",
    EdgeType.HAS_INCIDENT: "HAS_INCIDENT",
    EdgeType.DEPLOYED_BY: "DEPLOYED_BY",
    EdgeType.REFERENCES: "REFERENCES",
}


class CypherQueryBuilder:
    """Builds parameterised Cypher traversal queries.

    All external inputs (seed IDs, edge type strings) are passed as
    Cypher parameters ($seed_ids, $edge_types) — never interpolated into
    the query string — preventing Cypher injection.

    max_depth is formatted as an integer literal (never a string); it is
    validated at the Pydantic layer to be in [1, 5] before reaching this class.
    """

    def build_traversal(self, config: TraversalConfig) -> tuple[str, dict[str, object]]:
        """Return (cypher_query, parameters) ready for driver.session.run().

        Query shape:
          MATCH (seed)
          WHERE seed.entity_id IN $seed_ids
          MATCH path = (seed)-[r*1..<depth>]->(neighbour)
          WHERE ALL(rel IN relationships(path) WHERE type(rel) IN $edge_types)
            AND neighbour.entity_id <> seed.entity_id
          WITH seed, neighbour, length(path) AS hops, ...
          RETURN DISTINCT ...
          ORDER BY hops ASC
          LIMIT $limit
        """
        depth = config.max_depth  # validated int in [1, 5], safe to format as literal
        limit = config.max_nodes_per_seed * len(config.seed_entity_ids)
        edge_strs = [_EDGE_CYPHER[e] for e in config.edge_types]

        query = f"""
MATCH (seed)
WHERE seed.entity_id IN $seed_ids
MATCH path = (seed)-[r*1..{depth}]->(neighbour)
WHERE ALL(rel IN relationships(path) WHERE type(rel) IN $edge_types)
  AND neighbour.entity_id <> seed.entity_id
WITH seed, neighbour,
     length(path)                                   AS hops,
     relationships(path)[-1]                        AS last_rel,
     [rel IN relationships(path) | type(rel)]       AS rel_chain
RETURN DISTINCT
    neighbour.entity_id                             AS entity_id,
    labels(neighbour)[0]                            AS entity_type,
    neighbour.name                                  AS name,
    hops,
    seed.name + ' -[' + type(last_rel) + ']-> ' + neighbour.name AS path_summary,
    properties(neighbour)                           AS properties
ORDER BY hops ASC
LIMIT $limit
"""
        params: dict[str, object] = {
            "seed_ids": config.seed_entity_ids,
            "edge_types": edge_strs,
            "limit": limit,
        }
        return query.strip(), params

    def build_entity_lookup(self, entity_ids: list[str]) -> tuple[str, dict[str, object]]:
        """Fetch full node data for a list of known entity_ids (used by EntityLinker)."""
        query = """
MATCH (n)
WHERE n.entity_id IN $entity_ids
RETURN n.entity_id AS entity_id, labels(n)[0] AS entity_type,
       n.name AS name, properties(n) AS properties
"""
        return query.strip(), {"entity_ids": entity_ids}
