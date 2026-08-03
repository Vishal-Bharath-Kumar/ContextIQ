"""Tool registry population script.

TASK-BRD-18: Registers all enterprise MCP tools in the tool_registry database.

This script should be run during deployment or platform initialization to populate
the tool registry with all available enterprise capabilities.

Usage:
    docker compose exec api python scripts/registry/register_enterprise_tools.py
"""
from __future__ import annotations

import asyncio
import logging

from src.data.database import primary_session_factory
from src.registry.services.tool_registry_service import (
    DuplicateToolError,
    ToolRegistryService,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Tool definitions matching the implemented MCP tools
ENTERPRISE_TOOLS = [
    # Source Code Tools
    {
        "name": "search_code",
        "description": "Search for code across enterprise repositories using semantic and keyword search",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (natural language or code pattern)",
                },
                "repository": {
                    "type": "string",
                    "description": "Optional repository name to scope the search",
                },
                "language": {
                    "type": "string",
                    "description": "Optional programming language filter",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "explain_code",
        "description": "Get AI-generated explanation of code with enterprise context including dependencies and relationships",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file within the repository",
                },
                "repository": {
                    "type": "string",
                    "description": "Repository name",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional start line number",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional end line number",
                },
            },
            "required": ["file_path", "repository"],
        },
    },
    {
        "name": "search_repository",
        "description": "Search within a specific repository with optional path filtering",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name to search",
                },
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "path_filter": {
                    "type": "string",
                    "description": "Optional path pattern (e.g., src/**/*.py)",
                },
            },
            "required": ["repository", "query"],
        },
    },
    # Documentation Tools
    {
        "name": "search_documentation",
        "description": "Search enterprise documentation across Confluence, SharePoint, Notion, and Markdown repositories",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (natural language)",
                },
                "source": {
                    "type": "string",
                    "description": "Optional source filter (confluence, sharepoint, notion, markdown)",
                },
                "doc_type": {
                    "type": "string",
                    "description": "Optional document type (architecture, api, runbook, process)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "summarize_document",
        "description": "Generate an AI-powered summary of a document with key points",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "Unique document identifier",
                },
                "source": {
                    "type": "string",
                    "description": "Documentation source (confluence, sharepoint, etc.)",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum summary length in words",
                    "default": 500,
                },
            },
            "required": ["document_id", "source"],
        },
    },
    {
        "name": "architecture_search",
        "description": "Search architecture documentation including design docs, diagrams, ADRs, and system designs",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Architecture-related search query",
                },
                "component": {
                    "type": "string",
                    "description": "Optional component/service name to filter results",
                },
            },
            "required": ["query"],
        },
    },
    # Operations Tools
    {
        "name": "search_logs",
        "description": "Search logs across enterprise systems (Grafana Loki, Splunk, Datadog)",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Log search query (keywords, patterns, or Lucene syntax)",
                },
                "service": {
                    "type": "string",
                    "description": "Optional service/application name filter",
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range (1h, 24h, 7d, etc.)",
                    "default": "1h",
                },
                "level": {
                    "type": "string",
                    "description": "Optional log level filter (error, warn, info, debug)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum log entries",
                    "default": 50,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "deployment_history",
        "description": "View deployment history for a service including version, time, deployer, and status",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service/application name",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent deployments",
                    "default": 10,
                },
            },
            "required": ["service"],
        },
    },
    {
        "name": "service_health",
        "description": "Check health status of services including uptime, response time, error rate, and incidents",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Optional service name (if None, returns all services)",
                },
            },
            "required": [],
        },
    },
    # Knowledge Graph Tools
    {
        "name": "dependency_graph",
        "description": "Get dependency graph for a service including upstream and downstream dependencies",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service or repository name",
                },
                "depth": {
                    "type": "integer",
                    "description": "Relationship traversal depth",
                    "default": 2,
                },
            },
            "required": ["service"],
        },
    },
    {
        "name": "find_owner",
        "description": "Find owner(s) of a service, repository, or database including team and contact information",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "description": "Resource name",
                },
                "resource_type": {
                    "type": "string",
                    "description": "Type of resource (service, repository, database, api)",
                    "default": "service",
                },
            },
            "required": ["resource"],
        },
    },
    {
        "name": "related_services",
        "description": "Discover services related to a given service through shared dependencies or business capabilities",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name",
                },
                "relationship_type": {
                    "type": "string",
                    "description": "Optional filter (similar_function, shared_data, business_capability)",
                },
            },
            "required": ["service"],
        },
    },
    # AI Context Tools
    {
        "name": "generate_context",
        "description": "Generate optimized enterprise context through the full AI engineering pipeline",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "User's prompt or question",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum context size in tokens",
                    "default": 4000,
                },
                "compression_level": {
                    "type": "string",
                    "description": "Compression aggressiveness (low, medium, high)",
                    "default": "medium",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "compress_context",
        "description": "Apply AI-powered compression to reduce token usage while preserving semantic meaning",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Content to compress",
                },
                "target_compression": {
                    "type": "number",
                    "description": "Target compression ratio (0.8 = 80% reduction)",
                    "default": 0.8,
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "replay_execution",
        "description": "Replay a previous AI execution for debugging, auditing, or analysis",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "execution_id": {
                    "type": "string",
                    "description": "Unique execution identifier",
                },
            },
            "required": ["execution_id"],
        },
    },
]


async def register_tools() -> None:
    """Register all enterprise tools in the database."""
    logger.info("Starting enterprise tool registration...")
    
    async with primary_session_factory()() as session:
        # Note: Redis client would normally be injected; for registration we can pass None
        # as we don't need pub/sub during initial setup
        service = ToolRegistryService(session, redis_client=None)
        
        registered = 0
        skipped = 0
        failed = 0
        
        for tool_def in ENTERPRISE_TOOLS:
            try:
                await service.create_tool(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    input_schema=tool_def["input_schema"],
                    version=tool_def.get("version", "1.0.0"),
                )
                logger.info("✓ Registered: %s", tool_def["name"])
                registered += 1
                
            except DuplicateToolError:
                logger.info("⊘ Already exists: %s", tool_def["name"])
                skipped += 1
                
            except Exception as e:
                logger.error("✗ Failed to register %s: %s", tool_def["name"], e)
                failed += 1
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("Tool Registration Summary:")
        logger.info("  Registered: %d", registered)
        logger.info("  Skipped:    %d", skipped)
        logger.info("  Failed:     %d", failed)
        logger.info("  Total:      %d", len(ENTERPRISE_TOOLS))
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(register_tools())
