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
from src.gateway.tools.enterprise._local_tools import (
    CODE_ROOTS,
    build_error_response,
    build_tool_response,
    explain_code_file,
    json_text_response,
    search_workspace,
    workspace_coverage,
)
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
            matches = search_workspace(query, roots=CODE_ROOTS, suffixes=suffixes, limit=limit)
            results = build_tool_response(
                status="success" if matches else "empty",
                summary=(
                    f"Found {len(matches)} code match(es)."
                    if matches
                    else "No code matches were found for the supplied query."
                ),
                data={
                    "query": query,
                    "repository": repository or "ContextIQ",
                    "language": language or "all languages",
                    "results": matches,
                    "total": len(matches),
                },
                diagnostics={
                    "adapter": "workspace_search",
                    "source_availability": workspace_coverage(roots=CODE_ROOTS, suffixes=suffixes),
                    "degraded_reasons": [],
                },
            )
            results.update(
                {
                    "query": query,
                    "repository": repository or "ContextIQ",
                    "language": language or "all languages",
                    "results": matches,
                    "total": len(matches),
                }
            )
            
            logger.info(
                "search_code invoked: query=%s, repo=%s, lang=%s",
                query,
                repository,
                language,
            )
            
            return json_text_response(results)
            
        except Exception as e:
            logger.error("search_code failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Code search failed.",
                    error=e,
                    diagnostics={"adapter": "workspace_search"},
                )
            )

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
            explanation = explain_code_file(file_path, start_line=start_line, end_line=end_line)
            result = build_tool_response(
                status="success",
                summary="Generated a code explanation from the local workspace file.",
                data={**explanation, "repository": repository},
                diagnostics={"adapter": "workspace_file_read", "degraded_reasons": []},
            )
            result.update({**explanation, "repository": repository})
            
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
            return json_text_response(
                build_error_response(
                    summary="Code explanation failed.",
                    error=e,
                    diagnostics={"adapter": "workspace_file_read", "file_path": file_path},
                )
            )

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
            matches = search_workspace(
                query,
                roots=CODE_ROOTS,
                suffixes=None,
                limit=20,
                path_filter=path_filter,
            )
            result = build_tool_response(
                status="success" if matches else "empty",
                summary=(
                    f"Found {len(matches)} repository match(es)."
                    if matches
                    else "No repository matches were found for the supplied query."
                ),
                data={
                    "repository": repository or "ContextIQ",
                    "query": query,
                    "path_filter": path_filter,
                    "results": matches,
                },
                diagnostics={
                    "adapter": "workspace_search",
                    "source_availability": workspace_coverage(roots=CODE_ROOTS, path_filter=path_filter),
                    "degraded_reasons": [],
                },
            )
            result.update(
                {
                    "repository": repository or "ContextIQ",
                    "query": query,
                    "path_filter": path_filter,
                    "results": matches,
                }
            )
            
            logger.info(
                "search_repository invoked: %s in %s (filter: %s)",
                query,
                repository,
                path_filter,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("search_repository failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Repository search failed.",
                    error=e,
                    diagnostics={"adapter": "workspace_search", "path_filter": path_filter},
                )
            )
