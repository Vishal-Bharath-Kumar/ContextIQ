"""
Unit tests for TASK-US001-03: MCP ``initialize`` handshake handler.

Coverage targets (≥ 90% on handlers/initialize.py):
  - handle_initialize: valid request, unsupported version, server info
  - register_initialize_handler: parse error, valid dispatch, version error
  - InitializeRequest / ClientInfo validation (missing fields → parse error)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from src.gateway.handlers.initialize import (
    SUPPORTED_PROTOCOL_VERSIONS,
    handle_initialize,
    register_initialize_handler,
)
from src.gateway.schemas.mcp_types import (
    ClientInfo,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
    ServerInfo,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_request(
    protocol_version: str = "2024-11-05",
    client_name: str = "TestClient",
    client_version: str = "1.0",
    capabilities: dict | None = None,
) -> InitializeRequest:
    return InitializeRequest(
        protocolVersion=protocol_version,
        clientInfo=ClientInfo(name=client_name, version=client_version),
        capabilities=capabilities or {},
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestInitializeRequest:
    def test_valid_construction(self) -> None:
        req = _make_request()
        assert req.protocolVersion == "2024-11-05"
        assert req.clientInfo.name == "TestClient"
        assert req.clientInfo.version == "1.0"
        assert req.capabilities == {}

    def test_capabilities_defaults_to_empty_dict(self) -> None:
        req = InitializeRequest(
            protocolVersion="2024-11-05",
            clientInfo=ClientInfo(name="C", version="1"),
        )
        assert req.capabilities == {}

    def test_missing_client_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClientInfo(name="", version="1.0")

    def test_missing_protocol_version_raises(self) -> None:
        with pytest.raises(ValidationError):
            InitializeRequest(
                clientInfo=ClientInfo(name="C", version="1"),  # type: ignore[call-arg]
            )

    def test_missing_client_info_raises(self) -> None:
        with pytest.raises(ValidationError):
            InitializeRequest(
                protocolVersion="2024-11-05",
                # clientInfo omitted
            )  # type: ignore[call-arg]


class TestClientInfo:
    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClientInfo(version="1.0")  # type: ignore[call-arg]

    def test_missing_version_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClientInfo(name="X")  # type: ignore[call-arg]


class TestInitializeResult:
    def test_default_protocol_version(self) -> None:
        result = InitializeResult(
            serverInfo=ServerInfo(name="GW", version="0.1.0"),
        )
        assert result.protocolVersion == "2024-11-05"

    def test_default_capabilities(self) -> None:
        result = InitializeResult(
            serverInfo=ServerInfo(name="GW", version="0.1.0"),
        )
        assert result.capabilities.tools == {"listChanged": True}


# ---------------------------------------------------------------------------
# handle_initialize — valid request
# ---------------------------------------------------------------------------

class TestHandleInitializeValid:
    @pytest.mark.asyncio
    async def test_returns_initialize_result(self) -> None:
        req = _make_request()
        result = await handle_initialize(req)
        assert isinstance(result, InitializeResult)

    @pytest.mark.asyncio
    async def test_server_name_is_gateway(self) -> None:
        req = _make_request()
        result = await handle_initialize(req)
        assert result.serverInfo.name == "ContextIQ MCP Gateway"

    @pytest.mark.asyncio
    async def test_server_version_matches_settings(self) -> None:
        from src.gateway.config import settings

        req = _make_request()
        result = await handle_initialize(req)
        assert result.serverInfo.version == settings.server_version

    @pytest.mark.asyncio
    async def test_echoes_supported_protocol_version(self) -> None:
        req = _make_request(protocol_version="2024-11-05")
        result = await handle_initialize(req)
        assert result.protocolVersion == "2024-11-05"

    @pytest.mark.asyncio
    async def test_capabilities_advertise_tools_list_changed(self) -> None:
        req = _make_request()
        result = await handle_initialize(req)
        assert result.capabilities.tools.get("listChanged") is True

    @pytest.mark.asyncio
    async def test_logs_client_info(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        req = _make_request(client_name="Cursor", client_version="0.42.0")
        with caplog.at_level(logging.INFO, logger="src.gateway.handlers.initialize"):
            await handle_initialize(req)

        assert "Cursor" in caplog.text
        assert "0.42.0" in caplog.text


# ---------------------------------------------------------------------------
# handle_initialize — unsupported protocol version
# ---------------------------------------------------------------------------

class TestHandleInitializeUnsupportedVersion:
    @pytest.mark.asyncio
    async def test_raises_mcp_error(self) -> None:
        req = _make_request(protocol_version="1999-01-01")
        with pytest.raises(McpError) as exc_info:
            await handle_initialize(req)
        assert exc_info.value.error.code == -32600

    @pytest.mark.asyncio
    async def test_error_message_contains_version(self) -> None:
        bad_version = "0000-00-00"
        req = _make_request(protocol_version=bad_version)
        with pytest.raises(McpError) as exc_info:
            await handle_initialize(req)
        assert bad_version in exc_info.value.error.message

    @pytest.mark.asyncio
    async def test_empty_version_string_raises(self) -> None:
        req = _make_request(protocol_version="")
        with pytest.raises(McpError) as exc_info:
            await handle_initialize(req)
        assert exc_info.value.error.code == -32600


# ---------------------------------------------------------------------------
# register_initialize_handler — registration wrapper
# ---------------------------------------------------------------------------

class TestRegisterInitializeHandler:
    def _make_sdk_request(
        self,
        protocol_version: str = "2024-11-05",
        client_name: str = "TestClient",
        client_version: str = "1.0",
    ) -> MagicMock:
        """Build a minimal mcp.types.InitializeRequest mock."""
        from mcp import types as mcp_types

        caps = mcp_types.ClientCapabilities()
        params = mcp_types.InitializeRequestParams(
            protocolVersion=protocol_version,
            clientInfo=mcp_types.Implementation(name=client_name, version=client_version),
            capabilities=caps,
        )
        sdk_req = MagicMock()
        sdk_req.params = params
        return sdk_req

    def _make_low_level_server(self) -> MagicMock:
        server = MagicMock()
        server.request_handlers = {}
        return server

    def test_registers_handler_in_dict(self) -> None:
        from mcp import types as mcp_types

        server = self._make_low_level_server()
        register_initialize_handler(server)
        assert mcp_types.InitializeRequest in server.request_handlers

    @pytest.mark.asyncio
    async def test_valid_sdk_request_returns_server_result(self) -> None:
        from mcp import types as mcp_types

        server = self._make_low_level_server()
        register_initialize_handler(server)

        handler = server.request_handlers[mcp_types.InitializeRequest]
        sdk_req = self._make_sdk_request()
        result = await handler(sdk_req)

        assert isinstance(result, mcp_types.ServerResult)

    @pytest.mark.asyncio
    async def test_valid_sdk_request_server_name(self) -> None:
        from mcp import types as mcp_types

        server = self._make_low_level_server()
        register_initialize_handler(server)

        handler = server.request_handlers[mcp_types.InitializeRequest]
        sdk_req = self._make_sdk_request()
        result = await handler(sdk_req)

        init_result: mcp_types.InitializeResult = result.root
        assert init_result.serverInfo.name == "ContextIQ MCP Gateway"

    @pytest.mark.asyncio
    async def test_unsupported_version_raises_mcp_error(self) -> None:
        from mcp import types as mcp_types

        server = self._make_low_level_server()
        register_initialize_handler(server)

        handler = server.request_handlers[mcp_types.InitializeRequest]
        sdk_req = self._make_sdk_request(protocol_version="1900-01-01")

        with pytest.raises(McpError) as exc_info:
            await handler(sdk_req)
        assert exc_info.value.error.code == -32600

    @pytest.mark.asyncio
    async def test_malformed_client_info_raises_parse_error(self) -> None:
        from mcp import types as mcp_types

        server = self._make_low_level_server()
        register_initialize_handler(server)

        handler = server.request_handlers[mcp_types.InitializeRequest]

        # Simulate missing clientInfo.name via a broken params object
        bad_params = MagicMock()
        bad_params.protocolVersion = "2024-11-05"
        bad_params.capabilities = None
        # clientInfo.name raises AttributeError to simulate malformed data
        bad_info = MagicMock()
        bad_info.name = None  # will fail str validation
        bad_info.version = None
        bad_params.clientInfo = bad_info

        bad_sdk_req = MagicMock()
        bad_sdk_req.params = bad_params

        with pytest.raises(McpError) as exc_info:
            await handler(bad_sdk_req)
        assert exc_info.value.error.code == -32700


# ---------------------------------------------------------------------------
# SUPPORTED_PROTOCOL_VERSIONS constant
# ---------------------------------------------------------------------------

class TestSupportedVersionsConstant:
    def test_includes_2024_11_05(self) -> None:
        assert "2024-11-05" in SUPPORTED_PROTOCOL_VERSIONS

    def test_is_non_empty(self) -> None:
        assert len(SUPPORTED_PROTOCOL_VERSIONS) > 0
