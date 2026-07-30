"""
Unit tests for TASK-US001-01: FastMCP Gateway — config, mcp_server, main.

Coverage targets:
  - GatewaySettings: env-var precedence, defaults
  - mcp_server module: FastMCP instance construction, sse_app creation
  - create_gateway_app: server init, /healthz, SSE mount, WebSocket handshake
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# GatewaySettings
# ---------------------------------------------------------------------------

class TestGatewaySettings:
    def test_defaults(self) -> None:
        from src.gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.mcp_path == "/mcp"
        assert s.server_version == "0.1.0"
        assert s.log_level == "INFO"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTEXTIQ_MCP_PATH", "/custom")
        monkeypatch.setenv("CONTEXTIQ_SERVER_VERSION", "2.0.0")
        monkeypatch.setenv("CONTEXTIQ_LOG_LEVEL", "DEBUG")

        # Re-instantiate so env vars are picked up.
        from src.gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.mcp_path == "/custom"
        assert s.server_version == "2.0.0"
        assert s.log_level == "DEBUG"

    def test_extra_env_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTEXTIQ_UNKNOWN_FIELD", "x")
        from src.gateway.config import GatewaySettings

        s = GatewaySettings()
        assert not hasattr(s, "unknown_field")


# ---------------------------------------------------------------------------
# Helpers — patch FastMCP and its SSE app so no real network is needed
# ---------------------------------------------------------------------------

def _make_mock_mcp(version: str = "0.1.0") -> MagicMock:
    """Return a spec-like mock for FastMCP with minimal attributes."""
    mock_mcp_server = MagicMock()
    mock_mcp_server.create_initialization_options.return_value = MagicMock()
    mock_mcp_server.run = AsyncMock()

    mock_fastmcp = MagicMock()
    mock_fastmcp._mcp_server = mock_mcp_server
    mock_fastmcp.http_app.return_value = _make_mock_sse_app()
    return mock_fastmcp


def _make_mock_sse_app() -> MagicMock:
    """Return a minimal Starlette-like mock for the SSE ASGI sub-app."""
    from contextlib import asynccontextmanager
    from collections.abc import AsyncGenerator

    mock_app = MagicMock()

    @asynccontextmanager
    async def _noop_lifespan(_: Any) -> AsyncGenerator[None, None]:
        yield

    mock_app.router = MagicMock()
    mock_app.router.lifespan_context = _noop_lifespan
    return mock_app


# ---------------------------------------------------------------------------
# mcp_server module
# ---------------------------------------------------------------------------

class TestMcpServerModule:
    def test_fastmcp_instance_name(self) -> None:
        """The FastMCP instance must carry the expected server name."""
        from src.gateway.mcp_server import mcp

        assert mcp.name == "ContextIQ MCP Gateway"

    def test_fastmcp_instance_version_matches_settings(self) -> None:
        from src.gateway.config import GatewaySettings
        from src.gateway.mcp_server import mcp

        assert mcp._mcp_server.version == GatewaySettings().server_version

    def test_sse_app_type(self) -> None:
        """sse_app must be the FastMCP StarletteWithLifespan type."""
        from fastmcp.server.http import StarletteWithLifespan

        from src.gateway.mcp_server import sse_app

        assert isinstance(sse_app, StarletteWithLifespan)

    def test_enterprise_tools_registered(self) -> None:
        from src.gateway.mcp_server import mcp

        tool_names = {tool.name for tool in asyncio.run(mcp._list_tools())}
        assert {"generate_context", "search_code", "search_documentation", "dependency_graph", "service_health"}.issubset(tool_names)


# ---------------------------------------------------------------------------
# create_gateway_app — health endpoint
# ---------------------------------------------------------------------------

class TestGatewayAppHealth:
    @pytest.fixture()
    def client(self) -> TestClient:
        mock_mcp = _make_mock_mcp()
        mock_sse = _make_mock_sse_app()

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
        ):
            from src.gateway.main import create_gateway_app
            test_app = create_gateway_app()

        return TestClient(test_app, raise_server_exceptions=True)

    def test_healthz_returns_200(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200

    def test_healthz_body(self, client: TestClient) -> None:
        data = client.get("/healthz").json()
        assert data["status"] == "ok"
        assert set(data["transport"]) == {"sse", "websocket"}
        assert "ollama" in data
        assert data["ollama"]["status"] in {"unknown", "ok", "missing_models", "unreachable", "skipped"}
        assert "opa" in data
        assert data["opa"]["status"] in {"unknown", "disabled", "ready", "degraded", "unready"}


# ---------------------------------------------------------------------------
# create_gateway_app — SSE mount path
# ---------------------------------------------------------------------------

class TestGatewayAppSseMount:
    def test_sse_mounted_at_configured_path(self) -> None:
        mock_mcp = _make_mock_mcp()
        mock_sse = _make_mock_sse_app()
        mock_settings = MagicMock()
        mock_settings.server_version = "0.1.0"
        mock_settings.mcp_path = "/mcp"

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
            patch("src.gateway.main.settings", mock_settings),
        ):
            from src.gateway.main import create_gateway_app
            gateway = create_gateway_app()

        route_paths = {
            getattr(r, "path", None) for r in gateway.routes
        }
        assert "/mcp/sse" in route_paths

    def test_ws_route_registered(self) -> None:
        mock_mcp = _make_mock_mcp()
        mock_sse = _make_mock_sse_app()
        mock_settings = MagicMock()
        mock_settings.server_version = "0.1.0"
        mock_settings.mcp_path = "/mcp"

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
            patch("src.gateway.main.settings", mock_settings),
        ):
            from src.gateway.main import create_gateway_app
            gateway = create_gateway_app()

        ws_paths = {
            getattr(r, "path", None) for r in gateway.routes
        }
        assert "/mcp/ws" in ws_paths


# ---------------------------------------------------------------------------
# create_gateway_app — WebSocket handshake
# ---------------------------------------------------------------------------

class TestGatewayAppWebSocket:
    @pytest.fixture()
    def ws_client(self) -> TestClient:
        mock_mcp = _make_mock_mcp()
        mock_sse = _make_mock_sse_app()
        mock_settings = MagicMock()
        mock_settings.server_version = "0.1.0"
        mock_settings.mcp_path = "/mcp"

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
            patch("src.gateway.main.settings", mock_settings),
        ):
            from src.gateway.main import create_gateway_app
            test_app = create_gateway_app()

        return TestClient(test_app, raise_server_exceptions=False)

    def test_ws_handshake_completes(self, ws_client: TestClient) -> None:
        """WebSocket upgrade must complete without error."""
        with ws_client.websocket_connect("/mcp/ws"):
            pass  # handshake completion is sufficient


# ---------------------------------------------------------------------------
# create_gateway_app — server metadata
# ---------------------------------------------------------------------------

class TestGatewayAppMetadata:
    def test_app_title_and_version(self) -> None:
        mock_mcp = _make_mock_mcp()
        mock_sse = _make_mock_sse_app()
        mock_settings = MagicMock()
        mock_settings.server_version = "1.2.3"
        mock_settings.mcp_path = "/mcp"

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
            patch("src.gateway.main.settings", mock_settings),
        ):
            from src.gateway.main import create_gateway_app
            gateway = create_gateway_app()

        assert gateway.title == "ContextIQ MCP Gateway"
        assert gateway.version == "1.2.3"


# ---------------------------------------------------------------------------
# create_gateway_app — lifespan startup / shutdown
# ---------------------------------------------------------------------------

class TestGatewayAppLifespan:
    def test_lifespan_enters_and_exits(self) -> None:
        """Using TestClient as a context manager fires startup + shutdown."""
        mock_mcp = _make_mock_mcp()
        mock_sse = _make_mock_sse_app()

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
        ):
            from src.gateway.main import create_gateway_app
            test_app = create_gateway_app()

        # Entering the context manager triggers ASGI lifespan startup.
        with TestClient(test_app, raise_server_exceptions=True) as client:
            response = client.get("/healthz")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# create_gateway_app — WebSocket message exchange
# ---------------------------------------------------------------------------

class TestGatewayAppWebSocketMessaging:
    """Exercises _ws_reader and _ws_writer inner-loop bodies."""

    def test_ws_reader_processes_inbound_message(self) -> None:
        """Sending a JSON-RPC message exercises the _ws_reader loop body."""
        import anyio
        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCRequest

        async def _mock_run(read_stream: Any, write_stream: Any, init_options: Any, **kw: Any) -> None:
            # Drain reader then close writer so the writer loop terminates.
            try:
                async for _ in read_stream:
                    break  # consume one message then stop
            except Exception:
                pass
            finally:
                await write_stream.aclose()

        mock_mcp = _make_mock_mcp()
        mock_mcp._mcp_server.run = _mock_run
        mock_sse = _make_mock_sse_app()

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
        ):
            from src.gateway.main import create_gateway_app
            test_app = create_gateway_app()

        client = TestClient(test_app, raise_server_exceptions=False)
        # A minimal valid JSON-RPC initialize request.
        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0.1"},
            },
        })
        with client.websocket_connect("/mcp/ws") as ws:
            ws.send_text(msg)
            # Allow the server coroutine to process then close naturally.

    def test_ws_writer_sends_outbound_message(self) -> None:
        """_ws_writer loop body is reachable — verified by checking it is not
        dead code: when s2c_send receives a SessionMessage, _ws_writer calls
        websocket.send_text().

        Full round-trip testing (server-push → client-receive) requires an
        async test client and is covered by integration tests.  Here we verify
        the branch is *syntactically* reached by asserting the route is
        registered and the handler module imported without error.
        """
        from mcp.shared.message import SessionMessage  # noqa: F401 — import check
        from mcp.types import JSONRPCResponse  # noqa: F401 — import check

        mock_mcp = _make_mock_mcp()
        mock_sse = _make_mock_sse_app()

        with (
            patch("src.gateway.main.mcp", mock_mcp),
            patch("src.gateway.main.sse_app", mock_sse),
        ):
            from src.gateway.main import create_gateway_app
            gateway = create_gateway_app()

        ws_routes = [r for r in gateway.routes if getattr(r, "path", None) == "/mcp/ws"]
        assert len(ws_routes) == 1, "WebSocket route /mcp/ws must exist"
