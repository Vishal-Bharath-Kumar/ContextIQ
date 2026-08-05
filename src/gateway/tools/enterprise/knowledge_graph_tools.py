"""Knowledge graph relationship tools.

TASK-BRD-18: Implements MCP tools for knowledge graph capabilities:
- dependency_graph: Visualize service dependencies
- find_owner: Find owners of services/repos
- related_services: Discover related services
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastmcp import FastMCP
from neo4j import AsyncGraphDatabase
from src.gateway.tools.enterprise._local_tools import (
    build_error_response,
    build_tool_response,
    json_text_response,
    latest_file_authors,
    service_graph,
    service_graph_diagnostics,
)
from src.knowledge_graph.stores.neo4j_store import Neo4jSettings
from mcp.types import TextContent

logger = logging.getLogger(__name__)


def _neo4j_enabled() -> bool:
    return bool(os.environ.get("NEO4J_URI"))


def _clamp_depth(depth: int) -> int:
    return max(1, min(depth, 4))


async def _run_neo4j_query(query: str, **params: object) -> list[dict[str, Any]]:
    settings = Neo4jSettings()
    driver = AsyncGraphDatabase.driver(
        settings.uri,
        auth=(settings.username, settings.password),
    )
    try:
        async with driver.session(database=settings.database) as session:
            result = await session.run(query, **params)
            return [dict(record) async for record in result]
    finally:
        await driver.close()


def _neo4j_diagnostics() -> dict[str, Any]:
    return {
        "adapter": "neo4j",
        "source_available": True,
        "degraded_reasons": [],
    }


async def _dependency_graph_from_neo4j(service: str, depth: int) -> dict[str, Any] | None:
    normalized_service = service.strip().lower()
    rows = await _run_neo4j_query(
        """
        MATCH (root)
        WHERE toLower(root.name) = $service
        RETURN root.name AS name
        LIMIT 1
        """,
        service=normalized_service,
    )
    if not rows:
        return None

    traversal_depth = _clamp_depth(depth)
    upstream_rows = await _run_neo4j_query(
        f"""
        MATCH (root)
        WHERE toLower(root.name) = $service
        MATCH (root)-[:DEPENDS_ON*1..{traversal_depth}]->(node)
        RETURN DISTINCT coalesce(node.type, head(labels(node)), 'Entity') AS type,
                        node.name AS name
        ORDER BY name
        """,
        service=normalized_service,
    )
    downstream_rows = await _run_neo4j_query(
        f"""
        MATCH (root)
        WHERE toLower(root.name) = $service
        MATCH (node)-[:DEPENDS_ON*1..{traversal_depth}]->(root)
        RETURN DISTINCT coalesce(node.type, head(labels(node)), 'Entity') AS type,
                        node.name AS name
        ORDER BY name
        """,
        service=normalized_service,
    )

    upstream = [{"type": str(row["type"]), "name": str(row["name"])} for row in upstream_rows]
    downstream = [{"type": str(row["type"]), "name": str(row["name"])} for row in downstream_rows]
    return {
        "service": rows[0]["name"],
        "depth": traversal_depth,
        "dependencies": {
            "upstream": upstream,
            "downstream": downstream,
        },
        "graph_nodes": 1 + len(upstream) + len(downstream),
    }


async def _owners_from_neo4j(resource: str) -> list[dict[str, Any]]:
    rows = await _run_neo4j_query(
        """
        MATCH (resource)-[:OWNED_BY]->(owner)
        WHERE toLower(resource.name) = $resource
        RETURN DISTINCT owner.name AS owner,
                        coalesce(owner.type, head(labels(owner)), 'Entity') AS owner_type,
                        owner.entity_id AS entity_id
        ORDER BY owner
        """,
        resource=resource.strip().lower(),
    )
    return [
        {
            "owner": str(row["owner"]),
            "owner_type": str(row["owner_type"]),
            "entity_id": str(row["entity_id"]),
            "source": "knowledge_graph",
        }
        for row in rows
    ]


async def _related_services_from_neo4j(service: str) -> dict[str, Any] | None:
    normalized_service = service.strip().lower()
    rows = await _run_neo4j_query(
        """
        MATCH (root)
        WHERE toLower(root.name) = $service
        RETURN root.name AS name
        LIMIT 1
        """,
        service=normalized_service,
    )
    if not rows:
        return None

    upstream_rows = await _run_neo4j_query(
        """
        MATCH (root)-[:DEPENDS_ON]->(candidate)
        WHERE toLower(root.name) = $service
        RETURN DISTINCT candidate.name AS service,
                        'upstream_dependency' AS relationship,
                        0.85 AS confidence
        ORDER BY service
        """,
        service=normalized_service,
    )
    downstream_rows = await _run_neo4j_query(
        """
        MATCH (candidate)-[:DEPENDS_ON]->(root)
        WHERE toLower(root.name) = $service
        RETURN DISTINCT candidate.name AS service,
                        'downstream_dependency' AS relationship,
                        0.9 AS confidence
        ORDER BY service
        """,
        service=normalized_service,
    )
    shared_rows = await _run_neo4j_query(
        """
        MATCH (root)-[:DEPENDS_ON]->(shared)<-[:DEPENDS_ON]-(candidate)
        WHERE toLower(root.name) = $service
          AND candidate <> root
        RETURN candidate.name AS service,
               collect(DISTINCT shared.name) AS shared_dependencies
        ORDER BY service
        """,
        service=normalized_service,
    )

    related: dict[tuple[str, str], dict[str, Any]] = {}
    for row in upstream_rows + downstream_rows:
        key = (str(row["service"]), str(row["relationship"]))
        related[key] = {
            "service": str(row["service"]),
            "relationship": str(row["relationship"]),
            "confidence": float(row["confidence"]),
        }
    for row in shared_rows:
        service_name = str(row["service"])
        key = (service_name, "shared_dependency")
        shared_dependencies = [str(item) for item in row["shared_dependencies"] if item]
        related[key] = {
            "service": service_name,
            "relationship": "shared_dependency",
            "confidence": min(0.5 + (0.1 * len(shared_dependencies)), 0.8),
            "shared_dependencies": shared_dependencies,
        }

    return {
        "service": rows[0]["name"],
        "related": sorted(related.values(), key=lambda item: (item["service"], item["relationship"])),
    }


def register_knowledge_graph_tools(mcp: FastMCP, graph_service: Any = None) -> None:
    """Register knowledge graph tools on the MCP server.
    
    Parameters
    ----------
    mcp:
        FastMCP server instance
    graph_service:
        Neo4j graph service for relationship queries
    """

    @mcp.tool()
    async def dependency_graph(
        service: str,
        depth: int = 2,
    ) -> list[TextContent]:
        """Get dependency graph for a service or repository.
        
        Retrieves upstream and downstream dependencies from the knowledge graph
        including services, databases, APIs, and repositories.
        
        Parameters
        ----------
        service:
            Service or repository name
        depth:
            Relationship traversal depth (default: 2)
            
        Returns
        -------
        list[TextContent]:
            Dependency graph with nodes and relationships
        """
        try:
            if _neo4j_enabled():
                payload = await _dependency_graph_from_neo4j(service, depth)
                if payload is not None:
                    result = build_tool_response(
                        status="success",
                        summary=f"Resolved dependency graph for '{payload['service']}'.",
                        data=payload,
                        diagnostics=_neo4j_diagnostics(),
                    )
                    result.update(payload)
                    logger.info(
                        "dependency_graph invoked via neo4j: service=%s, depth=%d",
                        service,
                        payload["depth"],
                    )
                    return json_text_response(result)

            graph = service_graph()
            graph_diagnostics = service_graph_diagnostics()
            info = graph.get(service)
            if not graph:
                result = build_tool_response(
                    status="degraded",
                    summary="Dependency graph metadata is unavailable in this runtime.",
                    data={"service": service, "depth": depth, "dependencies": {"upstream": [], "downstream": []}, "graph_nodes": 0},
                    diagnostics=graph_diagnostics,
                )
                result.update({"service": service, "depth": depth, "dependencies": {"upstream": [], "downstream": []}, "graph_nodes": 0})
                return json_text_response(result)

            if info is None:
                result = build_tool_response(
                    status="empty",
                    summary=f"Service '{service}' was not found in the available dependency graph.",
                    data={
                        "service": service,
                        "depth": depth,
                        "dependencies": {"upstream": [], "downstream": []},
                        "graph_nodes": len(graph),
                        "available_services": sorted(graph.keys())[:25],
                    },
                    diagnostics=graph_diagnostics,
                )
                result.update(result["data"])
                return json_text_response(result)

            downstream = sorted([name for name, data in graph.items() if service in data.get("depends_on", [])])
            payload = {
                "service": service,
                "depth": depth,
                "dependencies": {
                    "upstream": [{"type": "service", "name": name} for name in info.get("depends_on", [])],
                    "downstream": [{"type": "service", "name": name} for name in downstream],
                },
                "graph_nodes": 1 + len(info.get("depends_on", [])) + len(downstream),
            }
            result = build_tool_response(
                status="success",
                summary=f"Resolved dependency graph for '{service}'.",
                data=payload,
                diagnostics=graph_diagnostics,
            )
            result.update(payload)
            
            logger.info(
                "dependency_graph invoked: service=%s, depth=%d",
                service,
                depth,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("dependency_graph failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Dependency graph lookup failed.",
                    error=e,
                    diagnostics={"adapter": "docker_compose"},
                )
            )

    @mcp.tool()
    async def find_owner(
        resource: str,
        resource_type: str = "service",
    ) -> list[TextContent]:
        """Find owner(s) of a service, repository, or database.
        
        Looks up ownership information from the knowledge graph including
        team, primary contacts, and on-call rotation.
        
        Parameters
        ----------
        resource:
            Resource name (service, repo, database, etc.)
        resource_type:
            Type of resource (service, repository, database, api)
            
        Returns
        -------
        list[TextContent]:
            Owner information with contact details
        """
        try:
            if _neo4j_enabled():
                owners = await _owners_from_neo4j(resource)
                if owners:
                    result = build_tool_response(
                        status="success",
                        summary=f"Resolved {len(owners)} owner candidate(s) from the knowledge graph.",
                        data={"resource": resource, "resource_type": resource_type, "owners": owners},
                        diagnostics=_neo4j_diagnostics(),
                    )
                    result.update({"resource": resource, "resource_type": resource_type, "owners": owners})
                    logger.info(
                        "find_owner invoked via neo4j: resource=%s, type=%s",
                        resource,
                        resource_type,
                    )
                    return json_text_response(result)

            owners = latest_file_authors(resource)
            result = build_tool_response(
                status="success" if owners else "empty",
                summary=(
                    f"Resolved {len(owners)} owner candidate(s)."
                    if owners
                    else "No owner candidates were found from repository history."
                ),
                data={"resource": resource, "resource_type": resource_type, "owners": owners},
                diagnostics={"adapter": "git_history", "degraded_reasons": []},
            )
            result.update({"resource": resource, "resource_type": resource_type, "owners": owners})
            
            logger.info(
                "find_owner invoked: resource=%s, type=%s",
                resource,
                resource_type,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("find_owner failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Owner lookup failed.",
                    error=e,
                    diagnostics={"adapter": "git_history"},
                )
            )

    @mcp.tool()
    async def related_services(
        service: str,
        relationship_type: str | None = None,
    ) -> list[TextContent]:
        """Discover services related to a given service.
        
        Finds services with similar functionality, shared dependencies,
        or related business capabilities from the knowledge graph.
        
        Parameters
        ----------
        service:
            Service name
        relationship_type:
            Optional filter (similar_function, shared_data, business_capability)
            
        Returns
        -------
        list[TextContent]:
            Related services with relationship descriptions
        """
        try:
            if _neo4j_enabled():
                payload = await _related_services_from_neo4j(service)
                if payload is not None:
                    if relationship_type is not None:
                        payload["related"] = [
                            item for item in payload["related"] if item["relationship"] == relationship_type
                        ]
                    payload["relationship_type"] = relationship_type
                    result = build_tool_response(
                        status="success" if payload["related"] else "empty",
                        summary=(
                            f"Resolved {len(payload['related'])} related service(s) from the knowledge graph."
                            if payload["related"]
                            else f"No related services were found for '{payload['service']}'."
                        ),
                        data=payload,
                        diagnostics=_neo4j_diagnostics(),
                    )
                    result.update(payload)
                    logger.info(
                        "related_services invoked via neo4j: service=%s, type=%s",
                        service,
                        relationship_type,
                    )
                    return json_text_response(result)

            graph = service_graph()
            graph_diagnostics = service_graph_diagnostics()
            if not graph:
                result = build_tool_response(
                    status="degraded",
                    summary="Related-service graph metadata is unavailable in this runtime.",
                    data={"service": service, "relationship_type": relationship_type, "related": []},
                    diagnostics=graph_diagnostics,
                )
                result.update({"service": service, "relationship_type": relationship_type, "related": []})
                return json_text_response(result)

            if service not in graph:
                result = build_tool_response(
                    status="empty",
                    summary=f"Service '{service}' was not found in the available service graph.",
                    data={
                        "service": service,
                        "relationship_type": relationship_type,
                        "related": [],
                        "available_services": sorted(graph.keys())[:25],
                    },
                    diagnostics=graph_diagnostics,
                )
                result.update(result["data"])
                return json_text_response(result)

            base = graph.get(service, {"depends_on": []})
            base_deps = set(base.get("depends_on", []))
            related = []
            for candidate, data in graph.items():
                if candidate == service:
                    continue
                shared = sorted(base_deps & set(data.get("depends_on", [])))
                if service in data.get("depends_on", []):
                    related.append({"service": candidate, "relationship": "downstream_dependency", "confidence": 0.9})
                elif candidate in base_deps:
                    related.append({"service": candidate, "relationship": "upstream_dependency", "confidence": 0.85})
                elif shared:
                    related.append({"service": candidate, "relationship": "shared_dependency", "confidence": min(0.5 + (0.1 * len(shared)), 0.8), "shared_dependencies": shared})
            payload = {"service": service, "relationship_type": relationship_type, "related": related}
            result = build_tool_response(
                status="success" if related else "empty",
                summary=(
                    f"Resolved {len(related)} related service(s)."
                    if related
                    else f"No related services were found for '{service}'."
                ),
                data=payload,
                diagnostics=graph_diagnostics,
            )
            result.update(payload)
            
            logger.info(
                "related_services invoked: service=%s, type=%s",
                service,
                relationship_type,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("related_services failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Related-services lookup failed.",
                    error=e,
                    diagnostics={"adapter": "docker_compose"},
                )
            )
