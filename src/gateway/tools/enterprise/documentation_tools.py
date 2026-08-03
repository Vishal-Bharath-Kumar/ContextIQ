"""Documentation and knowledge search tools.

TASK-BRD-18: Implements MCP tools for documentation capabilities:
- search_documentation: Search across enterprise documentation
- summarize_document: Generate document summaries
- architecture_search: Search architecture-specific content
"""
from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from src.gateway.tools.enterprise._local_tools import DOC_ROOT, json_text_response, search_workspace, summarize_document_path
from mcp.types import TextContent

logger = logging.getLogger(__name__)


def register_documentation_tools(mcp: FastMCP, knowledge_service: Any = None) -> None:
    """Register documentation tools on the MCP server.
    
    Parameters
    ----------
    mcp:
        FastMCP server instance
    knowledge_service:
        Knowledge source service for accessing indexed documentation
    """

    @mcp.tool()
    async def search_documentation(
        query: str,
        source: str | None = None,
        doc_type: str | None = None,
        limit: int = 10,
    ) -> list[TextContent]:
        """Search enterprise documentation, wikis, and knowledge bases.
        
        Searches across Confluence, SharePoint, Notion, Markdown docs, and other
        configured documentation sources.
        
        Parameters
        ----------
        query:
            Search query (natural language)
        source:
            Optional source filter (confluence, sharepoint, notion, markdown)
        doc_type:
            Optional document type (architecture, api, runbook, process)
        limit:
            Maximum results (default: 10)
            
        Returns
        -------
        list[TextContent]:
            Documentation search results with summaries
        """
        try:
            path_filter = None
            if doc_type:
                path_filter = f"**/*{doc_type}*.md"
            matches = search_workspace(query, roots=[DOC_ROOT], suffixes={".md"}, limit=limit, path_filter=path_filter)
            result = {
                "query": query,
                "source": source or "workspace-docs",
                "doc_type": doc_type,
                "results": matches,
                "total": len(matches),
                "status": "success",
            }
            
            logger.info(
                "search_documentation invoked: query=%s, source=%s, type=%s",
                query,
                source,
                doc_type,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("search_documentation failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

    @mcp.tool()
    async def summarize_document(
        document_id: str,
        source: str,
        max_length: int = 500,
    ) -> list[TextContent]:
        """Generate an AI-powered summary of a document.
        
        Retrieves the full document and generates a concise summary with key points.
        
        Parameters
        ----------
        document_id:
            Unique document identifier
        source:
            Documentation source (confluence, sharepoint, etc.)
        max_length:
            Maximum summary length in words
            
        Returns
        -------
        list[TextContent]:
            Document summary with metadata
        """
        try:
            result = {**summarize_document_path(document_id, max_words=max_length), "source": source, "status": "success"}
            
            logger.info(
                "summarize_document invoked: %s from %s",
                document_id,
                source,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("summarize_document failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

    @mcp.tool()
    async def architecture_search(
        query: str,
        component: str | None = None,
    ) -> list[TextContent]:
        """Search architecture documentation and diagrams.
        
        Specialized search for architecture-related content including design docs,
        C4 diagrams, ADRs (Architecture Decision Records), and system designs.
        
        Parameters
        ----------
        query:
            Architecture-related search query
        component:
            Optional component/service name to filter results
            
        Returns
        -------
        list[TextContent]:
            Architecture documentation results
        """
        try:
            results = search_workspace(
                query,
                roots=[DOC_ROOT],
                suffixes={".md"},
                limit=10,
                path_filter="**/*architecture*.md",
            )
            result = {
                "query": query,
                "component": component,
                "results": results,
                "status": "success",
            }
            
            logger.info(
                "architecture_search invoked: query=%s, component=%s",
                query,
                component,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("architecture_search failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})
