"""Async Neo4j traversal client — TASK-US029-03.

Implements ``GraphTraversalClient`` which executes the Cypher traversal query
built by ``CypherQueryBuilder``, enforces the 500 ms query timeout (AC-5),
deduplicates results by ``entity_id``, estimates token counts, and truncates
the result set to respect the caller's token budget (AC-6).

Also exposes ``lookup_entity_ids()`` used by ``EntityLinker``'s slow path.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time

from neo4j import AsyncDriver, AsyncGraphDatabase

from src.knowledge_graph.stores.neo4j_store import Neo4jSettings
from src.knowledge_graph.traversal.query_builder import CypherQueryBuilder
from src.knowledge_graph.traversal.schemas import (
    GraphContextItem,
    GraphTraversalResult,
    TraversalConfig,
)

logger = logging.getLogger(__name__)

_QUERY_BUILDER = CypherQueryBuilder()


class GraphTraversalClient:
    """Async Neo4j client for variable-depth entity traversal.

    Reuses ``Neo4jSettings`` for connection config — no duplicate settings class.
    The 500 ms hard timeout is enforced via ``asyncio.wait_for``; the fallback
    value is ``0.5`` when the settings object does not carry ``query_timeout_s``
    (i.e. plain ``Neo4jSettings`` which covers the connection-only config).
    """

    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self._settings = settings or Neo4jSettings()
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.username, self._settings.password),
        )

    async def traverse(self, config: TraversalConfig) -> GraphTraversalResult:
        """Execute a variable-depth traversal from seed entity IDs.

        Steps:
        1. Build parameterised Cypher via ``CypherQueryBuilder``.
        2. Run with ``asyncio.wait_for(timeout=query_timeout_s)``.
        3. Convert rows to ``GraphContextItem``, dedup by ``entity_id``, sort by hops.
        4. Truncate to ``token_budget``.
        5. Return ``GraphTraversalResult``.

        Raises:
            asyncio.TimeoutError: If the Neo4j query exceeds ``query_timeout_s``.
        """
        query, params = _QUERY_BUILDER.build_traversal(config)
        timeout_s: float = getattr(self._settings, "query_timeout_s", 0.5)
        start = time.monotonic()

        rows = await asyncio.wait_for(
            self._run_query(query, params),
            timeout=timeout_s,
        )

        duration_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "GraphTraversalClient: %d raw rows in %.1f ms for seeds=%s",
            len(rows),
            duration_ms,
            config.seed_entity_ids,
        )

        items = self._build_items(rows)
        items, truncated, total_tokens = self._apply_budget(items, config.token_budget)

        return GraphTraversalResult(
            items=items,
            total_tokens=total_tokens,
            query_duration_ms=duration_ms,
            seeds_used=config.seed_entity_ids,
            truncated=truncated,
        )

    async def lookup_entity_ids(self, names: list[str]) -> list[str]:
        """Resolve entity names to entity_ids via case-insensitive name match.

        Used by ``EntityLinker`` slow path when NER spans cannot be matched by
        fast embedding lookup.

        Args:
            names: Raw entity name strings (any case).

        Returns:
            List of matching ``entity_id`` strings, up to 50 results.
        """
        if not names:
            return []
        query = """
MATCH (n)
WHERE toLower(n.name) IN $names_lower
RETURN n.entity_id AS entity_id
LIMIT 50
"""
        params = {"names_lower": [n.strip().lower() for n in names]}
        rows = await self._run_query(query, params)
        return [r["entity_id"] for r in rows]

    async def close(self) -> None:
        """Close the underlying Neo4j driver and release connection pool resources."""
        await self._driver.close()

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _run_query(self, query: str, params: dict[str, object]) -> list[dict[str, object]]:
        """Execute a read query and return all records as plain dicts."""
        async with self._driver.session(database=self._settings.database) as session:
            result = await session.run(query, **params)
            return [dict(record) async for record in result]

    def _build_items(self, rows: list[dict[str, object]]) -> list[GraphContextItem]:
        """Convert raw Neo4j records to ``GraphContextItem``, dedup by ``entity_id``."""
        seen: set[str] = set()
        items: list[GraphContextItem] = []
        for row in rows:
            eid = str(row.get("entity_id") or "")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            text_repr = (
                f"{row.get('name', '')} "
                f"{row.get('path_summary', '')} "
                f"{row.get('properties', {})}"
            )
            token_count = max(1, math.ceil(len(text_repr) / 4))
            items.append(
                GraphContextItem(
                    entity_id=eid,
                    entity_type=str(row.get("entity_type") or "Entity"),
                    name=str(row.get("name") or ""),
                    hops=int(row.get("hops") or 1),
                    path_summary=str(row.get("path_summary") or ""),
                    properties=dict(row.get("properties") or {}),  # type: ignore[arg-type]
                    token_count=token_count,
                )
            )
        # Primary sort: ascending hops (closest neighbours first).
        items.sort(key=lambda x: x.hops)
        return items

    def _apply_budget(
        self,
        items: list[GraphContextItem],
        token_budget: int,
    ) -> tuple[list[GraphContextItem], bool, int]:
        """Greedily include items until ``token_budget`` is exhausted.

        Args:
            items:        Hop-ascending sorted list of candidate items.
            token_budget: Maximum tokens the result set may consume.

        Returns:
            Tuple of (included_items, was_truncated, total_tokens_used).
        """
        if token_budget <= 0:
            return [], bool(items), 0

        included: list[GraphContextItem] = []
        running_total = 0
        for item in items:
            if running_total + item.token_count > token_budget:
                return included, True, running_total
            included.append(item)
            running_total += item.token_count
        return included, False, running_total
