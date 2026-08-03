"""Direct payload tests for enterprise MCP tools.

These tests invoke the registered FastMCP tools and validate the JSON payloads
returned through the MCP content channel.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from src.gateway.context.request_context import RequestContext
from src.gateway.tools.enterprise.context_tools import register_context_tools
from src.gateway.tools.enterprise.documentation_tools import register_documentation_tools
from src.gateway.tools.enterprise.knowledge_graph_tools import register_knowledge_graph_tools
from src.gateway.tools.enterprise.operations_tools import register_operations_tools
from src.gateway.tools.enterprise.source_code_tools import register_source_code_tools


async def _invoke_tool(mcp: FastMCP, tool_name: str, arguments: dict) -> dict:
    tool = await mcp.get_tool(tool_name)
    result = await tool.run(arguments)
    assert result.content, f"{tool_name} returned no content"
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
class TestContextToolPayloads:
    async def test_generate_context_uses_context_service_payload(self) -> None:
        mcp = FastMCP("test-context")
        context_service = MagicMock()
        context_service.generate_context = AsyncMock(
            return_value={
                "prompt": "find auth flow",
                "requested_max_tokens": 2048,
                "compression_level": "high",
                "context": {"type": "context_package", "context": [{"path": "src/main.py"}]},
                "status": "success",
                "mode": "service",
            }
        )
        register_context_tools(mcp, context_service=context_service)

        payload = await _invoke_tool(
            mcp,
            "generate_context",
            {"prompt": "find auth flow", "max_tokens": 2048, "compression_level": "high"},
        )

        assert payload["status"] == "success"
        assert payload["mode"] == "service"
        assert payload["context"]["type"] == "context_package"

    async def test_compress_context_returns_deduped_payload(self) -> None:
        mcp = FastMCP("test-context")
        register_context_tools(mcp)

        payload = await _invoke_tool(
            mcp,
            "compress_context",
            {"content": "alpha\n\nalpha\n\nbeta", "target_compression": 0.5},
        )

        assert payload["status"] == "success"
        assert payload["original_length"] >= payload["compressed_length"]
        assert payload["removed_items"] == 1

    async def test_replay_execution_uses_context_service_payload(self) -> None:
        mcp = FastMCP("test-context")
        context_service = MagicMock()
        context_service.replay_execution = AsyncMock(
            return_value={
                "execution_id": "req-123",
                "status": "success",
                "trace": {"timeline": [], "model_selected": "gpt-4o-mini"},
            }
        )
        register_context_tools(mcp, context_service=context_service)

        payload = await _invoke_tool(mcp, "replay_execution", {"execution_id": "req-123"})

        assert payload["execution_id"] == "req-123"
        assert payload["status"] == "success"
        assert payload["trace"]["model_selected"] == "gpt-4o-mini"

    async def test_generate_context_pipeline_uses_request_context_identity(self) -> None:
        mcp = FastMCP("test-context")
        register_context_tools(mcp)

        request_ctx = RequestContext(
            request_id="req-123",
            user_id="user-123",
            username="admin",
            roles=frozenset({"admin"}),
            session_id="sess-123",
            trace_id=0,
        )

        async def _fake_pipeline(prompt: str) -> dict:
            return {
                "status": "complete",
                "final_response": {
                    "type": "context_package",
                    "prompt": prompt,
                    "intent": "debugging",
                    "context": [{"source_id": "github", "path": "src/auth.py", "content": "def login(): ..."}],
                    "governance": {"summary": {"audit_log": {"user": "user-123"}}},
                    "degraded_sources": [],
                },
            }

        with (
            patch("src.gateway.tools.enterprise.context_tools.get_request_context", return_value=request_ctx),
            patch("src.gateway.tools.enterprise.context_tools._try_pipeline_context", side_effect=_fake_pipeline),
        ):
            payload = await _invoke_tool(
                mcp,
                "generate_context",
                {"prompt": "debug auth flow", "max_tokens": 1024, "compression_level": "high"},
            )

        assert payload["status"] == "success"
        assert payload["mode"] == "pipeline"
        assert payload["context"]["governance"]["summary"]["audit_log"]["user"] == "user-123"

    async def test_generate_context_workspace_fallback_masks_secrets_and_populates_metrics(self) -> None:
        mcp = FastMCP("test-context")
        register_context_tools(mcp)

        candidate_models = [
            {
                "model_id": "gpt-4o-mini",
                "latency_tier": "fast",
                "capabilities": ["chat"],
                "context_window": 32000,
                "cost_per_1k_tokens": 0.5,
            },
            {
                "model_id": "ollama/llama3.2",
                "latency_tier": "medium",
                "capabilities": ["chat", "code"],
                "context_window": 128000,
                "cost_per_1k_tokens": 0.0,
            },
        ]
        secret_value = "ghp_1234567890abcdefghijklmnopqrstuvABCDE1"
        matches = [
            {
                "path": "src/api/auth.py",
                "title": "auth",
                "line": 14,
                "snippet": f'Authorization: Bearer {secret_value} password="TopSecret123!"',
                "score": 14.2,
            }
        ]

        with (
            patch("src.gateway.tools.enterprise.context_tools._try_pipeline_context", AsyncMock(return_value=None)),
            patch("src.gateway.tools.enterprise.context_tools.search_workspace", return_value=matches),
            patch("src.gateway.tools.enterprise.context_tools._candidate_models", AsyncMock(return_value=candidate_models)),
        ):
            payload = await _invoke_tool(
                mcp,
                "generate_context",
                {
                    "prompt": "For the current workspace repository, identify the main services/components and describe the end-to-end workflow.",
                    "max_tokens": 1024,
                    "compression_level": "high",
                },
            )

        assert payload["status"] == "success"
        assert payload["mode"] == "workspace_fallback"
        assert payload["routing"]["selected_model"] == "ollama/llama3.2"
        assert payload["compression"]["tokens_before"] is not None
        assert payload["compression"]["tokens_after"] is not None
        assert secret_value not in json.dumps(payload)
        assert payload["governance"]["redacted"] is True
        assert payload["governance"]["masking_counts"]

    async def test_generate_context_pipeline_backfills_routing_and_compression_metadata(self) -> None:
        mcp = FastMCP("test-context")
        register_context_tools(mcp)

        candidate_models = [
            {
                "model_id": "gpt-4o-mini",
                "latency_tier": "fast",
                "capabilities": ["chat"],
                "context_window": 32000,
                "cost_per_1k_tokens": 0.5,
            },
            {
                "model_id": "ollama/llama3.2",
                "latency_tier": "medium",
                "capabilities": ["chat", "code"],
                "context_window": 128000,
                "cost_per_1k_tokens": 0.0,
            },
        ]
        fake_pipeline = {
            "status": "complete",
            "intent_type": "architecture",
            "selected_model": "gpt-4o-mini",
            "model_routing_score": 0.0,
            "ranked_context": [
                {
                    "source_id": "github",
                    "path": "src/main.py",
                    "content": "create_app wires FastAPI routers, auth middleware, and the MCP mounts.",
                },
                {
                    "source_id": "docs",
                    "path": "docs/api/architecture/overview.md",
                    "content": "Architecture overview covering retrieval, ranking, compression, and governance.",
                },
            ],
            "final_response": {
                "type": "context_package",
                "intent": "architecture",
                "context": [
                    {
                        "source_id": "github",
                        "path": "src/main.py",
                        "content": "create_app wires FastAPI routers, auth middleware, and the MCP mounts.",
                    }
                ],
                "degraded_sources": [],
            },
        }

        with (
            patch("src.gateway.tools.enterprise.context_tools._try_pipeline_context", AsyncMock(return_value=fake_pipeline)),
            patch("src.gateway.tools.enterprise.context_tools._candidate_models", AsyncMock(return_value=candidate_models)),
        ):
            payload = await _invoke_tool(
                mcp,
                "generate_context",
                {
                    "prompt": "For the current workspace repository, identify the main services/components and describe the end-to-end workflow.",
                    "max_tokens": 2048,
                    "compression_level": "medium",
                },
            )

        assert payload["status"] == "success"
        assert payload["mode"] == "pipeline"
        assert payload["routing"]["selected_model"] == "ollama/llama3.2"
        assert payload["compression"]["tokens_before"] is not None
        assert payload["compression"]["tokens_after"] is not None
        assert payload["tokens_before_compression"] is not None
        assert payload["tokens_after_compression"] is not None

    async def test_generate_context_falls_back_when_pipeline_returns_degraded_empty_context(self) -> None:
        mcp = FastMCP("test-context")
        register_context_tools(mcp)

        candidate_models = [
            {
                "model_id": "ollama/llama3.2",
                "latency_tier": "medium",
                "capabilities": ["chat", "code"],
                "context_window": 128000,
                "cost_per_1k_tokens": 0.0,
            }
        ]
        fake_pipeline = {
            "status": "complete",
            "intent_type": "architecture",
            "selected_model": "gpt-4o-mini",
            "model_routing_score": 0.0,
            "degraded_sources": [{"source_id": "github", "error_type": "ConnectorAuthError", "message": "401"}],
            "final_response": {
                "type": "context_package",
                "intent": "architecture",
                "context": [],
                "degraded_sources": [{"source_id": "github", "error_type": "ConnectorAuthError", "message": "401"}],
            },
        }
        fallback_matches = [
            {"path": "docs/architecture/system.md", "title": "System", "line": 3, "snippet": "retrieval ranking compression governance", "score": 12.0}
        ]

        with (
            patch("src.gateway.tools.enterprise.context_tools._try_pipeline_context", AsyncMock(return_value=fake_pipeline)),
            patch("src.gateway.tools.enterprise.context_tools.search_workspace", return_value=fallback_matches),
            patch("src.gateway.tools.enterprise.context_tools._candidate_models", AsyncMock(return_value=candidate_models)),
        ):
            payload = await _invoke_tool(
                mcp,
                "generate_context",
                {"prompt": "ContextIQ architecture", "max_tokens": 1024, "compression_level": "medium"},
            )

        assert payload["status"] == "success"
        assert payload["mode"] == "workspace_fallback"
        assert payload["context"]["context"][0]["path"] == "docs/architecture/system.md"


@pytest.mark.asyncio
class TestSourceCodeToolPayloads:
    async def test_search_code_returns_workspace_results(self) -> None:
        mcp = FastMCP("test-source")
        register_source_code_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.source_code_tools.search_workspace",
            return_value=[{"path": "src/main.py", "line": 10, "snippet": "def create_app():", "score": 12.0}],
        ):
            payload = await _invoke_tool(mcp, "search_code", {"query": "create_app", "limit": 5})

        assert payload["status"] == "success"
        assert payload["results"][0]["path"] == "src/main.py"
        assert payload["total"] == 1

    async def test_search_code_empty_returns_diagnostics(self) -> None:
        mcp = FastMCP("test-source")
        register_source_code_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.source_code_tools.search_workspace",
            return_value=[],
        ):
            payload = await _invoke_tool(mcp, "search_code", {"query": "nonexistent symbol", "limit": 5})

        assert payload["status"] == "empty"
        assert payload["diagnostics"]["adapter"] == "workspace_search"
        assert "source_availability" in payload["diagnostics"]

    async def test_explain_code_returns_summary_fields(self) -> None:
        mcp = FastMCP("test-source")
        register_source_code_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.source_code_tools.explain_code_file",
            return_value={
                "file": "src/main.py",
                "language": "py",
                "lines": "1-20",
                "line_count": 20,
                "symbols": ["create_app"],
                "imports": ["fastapi"],
                "excerpt": "def create_app(): ...",
                "summary": "Creates the FastAPI app.",
            },
        ):
            payload = await _invoke_tool(
                mcp,
                "explain_code",
                {"file_path": "src/main.py", "repository": "ContextIQ", "start_line": 1, "end_line": 20},
            )

        assert payload["status"] == "success"
        assert payload["summary"] == "Creates the FastAPI app."
        assert payload["symbols"] == ["create_app"]


@pytest.mark.asyncio
class TestDocumentationToolPayloads:
    async def test_search_documentation_returns_matches(self) -> None:
        mcp = FastMCP("test-docs")
        register_documentation_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.documentation_tools.search_workspace",
            return_value=[{"path": "docs/api/architecture.md", "title": "API Architecture", "line": 3, "snippet": "gateway flow", "score": 11.2}],
        ):
            payload = await _invoke_tool(mcp, "search_documentation", {"query": "gateway", "limit": 3})

        assert payload["status"] == "success"
        assert payload["results"][0]["title"] == "API Architecture"

    async def test_summarize_document_returns_summary(self) -> None:
        mcp = FastMCP("test-docs")
        register_documentation_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.documentation_tools.summarize_document_path",
            return_value={
                "document_id": "docs/BRD.md",
                "title": "BRD",
                "summary": "Business requirements summary.",
                "key_points": ["Scope", "Constraints"],
                "word_count": 3,
            },
        ):
            payload = await _invoke_tool(
                mcp,
                "summarize_document",
                {"document_id": "docs/BRD.md", "source": "workspace", "max_length": 50},
            )

        assert payload["status"] == "success"
        assert payload["title"] == "BRD"
        assert payload["key_points"] == ["Scope", "Constraints"]


@pytest.mark.asyncio
class TestKnowledgeGraphToolPayloads:
    async def test_dependency_graph_returns_relationships(self) -> None:
        mcp = FastMCP("test-kg")
        register_knowledge_graph_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.knowledge_graph_tools.service_graph",
            return_value={
                "api": {"depends_on": ["postgres", "redis"], "ports": []},
                "admin-portal": {"depends_on": ["api"], "ports": []},
                "postgres": {"depends_on": [], "ports": []},
                "redis": {"depends_on": [], "ports": []},
            },
        ):
            payload = await _invoke_tool(mcp, "dependency_graph", {"service": "api", "depth": 2})

        assert payload["status"] == "success"
        assert payload["dependencies"]["upstream"][0]["name"] == "postgres"
        assert payload["dependencies"]["downstream"][0]["name"] == "admin-portal"

    async def test_dependency_graph_degrades_without_graph_metadata(self) -> None:
        mcp = FastMCP("test-kg")
        register_knowledge_graph_tools(mcp)

        with (
            patch("src.gateway.tools.enterprise.knowledge_graph_tools.service_graph", return_value={}),
            patch(
                "src.gateway.tools.enterprise.knowledge_graph_tools.service_graph_diagnostics",
                return_value={
                    "adapter": "docker_compose",
                    "source_available": False,
                    "compose_path": None,
                    "degraded_reasons": ["No docker-compose metadata was available in the runtime environment."],
                },
            ),
        ):
            payload = await _invoke_tool(mcp, "dependency_graph", {"service": "ContextIQ", "depth": 2})

        assert payload["status"] == "degraded"
        assert payload["diagnostics"]["source_available"] is False

    async def test_related_services_returns_structured_empty_when_service_missing(self) -> None:
        mcp = FastMCP("test-kg")
        register_knowledge_graph_tools(mcp)

        graph = {"api": {"depends_on": ["postgres"]}, "postgres": {"depends_on": []}}
        with (
            patch("src.gateway.tools.enterprise.knowledge_graph_tools.service_graph", return_value=graph),
            patch(
                "src.gateway.tools.enterprise.knowledge_graph_tools.service_graph_diagnostics",
                return_value={"adapter": "docker_compose", "source_available": True, "compose_path": "/tmp/docker-compose.yml", "degraded_reasons": []},
            ),
        ):
            payload = await _invoke_tool(mcp, "related_services", {"service": "ContextIQ"})

        assert payload["status"] == "empty"
        assert payload["related"] == []

    async def test_find_owner_returns_owner_list(self) -> None:
        mcp = FastMCP("test-kg")
        register_knowledge_graph_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.knowledge_graph_tools.latest_file_authors",
            return_value=[{"owner": "alice", "path": "src/main.py", "last_commit": "abc", "last_updated": "2026-07-29T00:00:00Z"}],
        ):
            payload = await _invoke_tool(mcp, "find_owner", {"resource": "main", "resource_type": "service"})

        assert payload["status"] == "success"
        assert payload["owners"][0]["owner"] == "alice"


@pytest.mark.asyncio
class TestOperationsToolPayloads:
    async def test_search_logs_uses_monitoring_service_when_available(self) -> None:
        mcp = FastMCP("test-ops")
        monitoring_service = MagicMock()
        monitoring_service.search_logs = AsyncMock(
            return_value=[{"timestamp": "2026-07-29T00:00:00Z", "level": "ERROR", "service": "api", "message": "boom"}]
        )
        register_operations_tools(mcp, monitoring_service=monitoring_service)

        payload = await _invoke_tool(mcp, "search_logs", {"query": "boom", "service": "api"})

        assert payload["status"] == "success"
        assert payload["logs"][0]["message"] == "boom"

    async def test_service_health_returns_snapshot_payload(self) -> None:
        mcp = FastMCP("test-ops")
        register_operations_tools(mcp)

        with patch(
            "src.gateway.tools.enterprise.operations_tools.service_health_snapshot",
            return_value=[{"service": "api", "status": "healthy", "ports": [{"host_port": 8000, "container_port": 8000, "reachable": True}], "depends_on": ["postgres"], "timestamp": "2026-07-29T00:00:00Z"}],
        ):
            payload = await _invoke_tool(mcp, "service_health", {"service": "api"})

        assert payload["status"] == "success"
        assert payload["health"][0]["service"] == "api"

    async def test_service_health_returns_structured_empty_for_unknown_service(self) -> None:
        mcp = FastMCP("test-ops")
        register_operations_tools(mcp)

        with (
            patch("src.gateway.tools.enterprise.operations_tools.service_graph", return_value={"api": {"depends_on": [], "ports": []}}),
            patch(
                "src.gateway.tools.enterprise.operations_tools.service_graph_diagnostics",
                return_value={"adapter": "docker_compose", "source_available": True, "compose_path": "/tmp/docker-compose.yml", "degraded_reasons": []},
            ),
        ):
            payload = await _invoke_tool(mcp, "service_health", {"service": "ContextIQ"})

        assert payload["status"] == "empty"
        assert payload["health"] == []
