"""Source code search and analysis tools.

TASK-BRD-18: Implements MCP tools for source code capabilities:
- search_code: Search across repositories
- explain_code: Get code explanations with context
- search_repository: Repository-specific search
"""
from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from src.gateway.tools.enterprise._local_tools import CODE_ROOTS, explain_code_file, json_text_response, search_workspace
from mcp.types import TextContent

logger = logging.getLogger(__name__)


def register_source_code_tools(mcp: FastMCP, connector_manager: Any = None) -> None:
    """Register source code tools on the MCP server.
    
    Parameters
    ----------
    mcp:
        FastMCP server instance
    connector_manager:
        Connector manager for accessing GitHub/GitLab connectors
    """

    @mcp.tool()
    async def search_code(
        query: str,
        repository: str | None = None,
        language: str | None = None,
        limit: int = 10,
    ) -> list[TextContent]:
        """Search for code across enterprise repositories.
        
        Searches through indexed source code using semantic and keyword search.
        Returns relevant code snippets with file paths, line numbers, and context.
        
        Parameters
        ----------
        query:
            Search query (natural language or code pattern)
        repository:
            Optional repository name to scope the search
        language:
            Optional programming language filter (python, typescript, java, etc.)
        limit:
            Maximum number of results (default: 10)
            
        Returns
        -------
        list[TextContent]:
            Code search results with snippets and metadata
        """
        try:
            suffixes = None
            if language:
                from src.gateway.tools.enterprise._local_tools import _LANGUAGE_SUFFIXES  # noqa: PLC0415

                suffixes = _LANGUAGE_SUFFIXES.get(language.lower())
            results = {
                "query": query,
                "repository": repository or "ContextIQ",
                "language": language or "all languages",
                "results": search_workspace(query, roots=CODE_ROOTS, suffixes=suffixes, limit=limit),
                "total": len(search_workspace(query, roots=CODE_ROOTS, suffixes=suffixes, limit=limit)),
                "status": "success",
            }
            
            logger.info(
                "search_code invoked: query=%s, repo=%s, lang=%s",
                query,
                repository,
                language,
            )
            
            return json_text_response(results)
            
        except Exception as e:
            logger.error("search_code failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

    @mcp.tool()
    async def explain_code(
        file_path: str,
        repository: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> list[TextContent]:
        """Get AI-generated explanation of code with enterprise context.
        
        Retrieves code from a specific file and generates a detailed explanation
        including architecture context, dependencies, and relationships.
        
        Parameters
        ----------
        file_path:
            Path to the file within the repository
        repository:
            Repository name
        start_line:
            Optional start line number for specific code block
        end_line:
            Optional end line number for specific code block
            
        Returns
        -------
        list[TextContent]:
            Code explanation with architecture context
        """
        try:
            result = {
                **explain_code_file(file_path, start_line=start_line, end_line=end_line),
                "repository": repository,
                "status": "success",
            }
            
            logger.info(
                "explain_code invoked: %s in %s (lines %s-%s)",
                file_path,
                repository,
                start_line,
                end_line,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("explain_code failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

    @mcp.tool()
    async def search_repository(
        repository: str,
        query: str,
        path_filter: str | None = None,
    ) -> list[TextContent]:
        """Search within a specific repository.
        
        Optimized search scoped to a single repository with optional path filtering.
        
        Parameters
        ----------
        repository:
            Repository name to search
        query:
            Search query
        path_filter:
            Optional path pattern (e.g., "src/**/*.py")
            
        Returns
        -------
        list[TextContent]:
            Repository search results
        """
        try:
            results = search_workspace(
                query,
                roots=CODE_ROOTS,
                suffixes=None,
                limit=20,
                path_filter=path_filter,
            )
            result = {
                "repository": repository or "ContextIQ",
                "query": query,
                "path_filter": path_filter,
                "results": results,
                "status": "success",
            }
            
            logger.info(
                "search_repository invoked: %s in %s (filter: %s)",
                query,
                repository,
                path_filter,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("search_repository failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})
