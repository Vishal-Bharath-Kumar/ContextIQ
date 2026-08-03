"""Knowledge graph relationship tools.

TASK-BRD-18: Implements MCP tools for knowledge graph capabilities:
- dependency_graph: Visualize service dependencies
- find_owner: Find owners of services/repos
- related_services: Discover related services
"""
from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from src.gateway.tools.enterprise._local_tools import json_text_response, latest_file_authors, service_graph
from mcp.types import TextContent

logger = logging.getLogger(__name__)


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
            graph = service_graph()
            info = graph.get(service, {"depends_on": [], "ports": []})
            downstream = sorted([name for name, data in graph.items() if service in data.get("depends_on", [])])
            result = {
                "service": service,
                "depth": depth,
                "dependencies": {
                    "upstream": [{"type": "service", "name": name} for name in info.get("depends_on", [])],
                    "downstream": [{"type": "service", "name": name} for name in downstream],
                },
                "graph_nodes": 1 + len(info.get("depends_on", [])) + len(downstream),
                "status": "success",
            }
            
            logger.info(
                "dependency_graph invoked: service=%s, depth=%d",
                service,
                depth,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("dependency_graph failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

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
            owners = latest_file_authors(resource)
            result = {
                "resource": resource,
                "resource_type": resource_type,
                "owners": owners,
                "status": "success" if owners else "unresolved",
            }
            
            logger.info(
                "find_owner invoked: resource=%s, type=%s",
                resource,
                resource_type,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("find_owner failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

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
            graph = service_graph()
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
            result = {
                "service": service,
                "relationship_type": relationship_type,
                "related": related,
                "status": "success",
            }
            
            logger.info(
                "related_services invoked: service=%s, type=%s",
                service,
                relationship_type,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("related_services failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})
