"""Operations and monitoring tools.

TASK-BRD-18: Implements MCP tools for operational capabilities:
- search_logs: Search logs across systems
- deployment_history: View deployment history
- service_health: Check service health status
"""
from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from src.gateway.tools.enterprise._local_tools import git_history, json_text_response, service_health_snapshot
from mcp.types import TextContent

logger = logging.getLogger(__name__)


def register_operations_tools(mcp: FastMCP, monitoring_service: Any = None) -> None:
    """Register operations tools on the MCP server.
    
    Parameters
    ----------
    mcp:
        FastMCP server instance
    monitoring_service:
        Service for accessing monitoring and logging systems
    """

    @mcp.tool()
    async def search_logs(
        query: str,
        service: str | None = None,
        time_range: str = "1h",
        level: str | None = None,
        limit: int = 50,
    ) -> list[TextContent]:
        """Search logs across enterprise systems.
        
        Searches logs from Grafana Loki, Splunk, Datadog, or other configured
        logging systems.
        
        Parameters
        ----------
        query:
            Log search query (keywords, patterns, or Lucene syntax)
        service:
            Optional service/application name filter
        time_range:
            Time range (1h, 24h, 7d, etc.)
        level:
            Optional log level filter (error, warn, info, debug)
        limit:
            Maximum log entries (default: 50)
            
        Returns
        -------
        list[TextContent]:
            Log search results with timestamps and context
        """
        try:
            logs = []
            if monitoring_service is not None and hasattr(monitoring_service, "search_logs"):
                logs = await monitoring_service.search_logs(query=query, service=service, time_range=time_range, level=level, limit=limit)
            result = {
                "query": query,
                "service": service or "all services",
                "time_range": time_range,
                "level": level,
                "logs": logs,
                "total": len(logs),
                "status": "success" if logs else "unavailable",
                "reason": None if logs else "No monitoring service configured for log aggregation.",
            }
            
            logger.info(
                "search_logs invoked: query=%s, service=%s, range=%s",
                query,
                service,
                time_range,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("search_logs failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

    @mcp.tool()
    async def deployment_history(
        service: str,
        limit: int = 10,
    ) -> list[TextContent]:
        """View deployment history for a service.
        
        Retrieves recent deployments with version, time, deployer, and status.
        
        Parameters
        ----------
        service:
            Service/application name
        limit:
            Number of recent deployments (default: 10)
            
        Returns
        -------
        list[TextContent]:
            Deployment history with metadata
        """
        try:
            deployments = git_history(limit, grep=service)
            if not deployments:
                deployments = git_history(limit)
            result = {
                "service": service,
                "deployments": deployments,
                "total": len(deployments),
                "status": "success",
            }
            
            logger.info("deployment_history invoked: service=%s", service)
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("deployment_history failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

    @mcp.tool()
    async def service_health(
        service: str | None = None,
    ) -> list[TextContent]:
        """Check health status of services.
        
        Retrieves current health status from monitoring systems including
        uptime, response time, error rate, and recent incidents.
        
        Parameters
        ----------
        service:
            Optional service name (if None, returns all services)
            
        Returns
        -------
        list[TextContent]:
            Service health metrics and status
        """
        try:
            health = service_health_snapshot(service)
            result = {
                "service": service or "all services",
                "health": health,
                "timestamp": health[0]["timestamp"] if health else None,
                "status": "success",
            }
            
            logger.info("service_health invoked: service=%s", service)
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("service_health failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})
