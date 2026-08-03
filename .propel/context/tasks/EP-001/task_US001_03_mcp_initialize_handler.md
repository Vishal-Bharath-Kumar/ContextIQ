# TASK-US001-03 — Implement MCP `initialize` Handshake Handler

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US001-03 |
| User Story | US-001 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Register the MCP `initialize` message handler that responds to the protocol handshake with the server's identity, version, and declared capabilities. This is the first message exchanged in every MCP session.

## Implementation Details

**Technology:** Python 3.11+, FastMCP

**File locations:**
- `src/gateway/handlers/initialize.py` — `initialize` handler function
- `src/gateway/schemas/mcp_types.py` — Pydantic models for `InitializeRequest` / `InitializeResult`
- `tests/gateway/test_initialize_handler.py` — unit and integration tests

**Key implementation steps:**

1. Define `InitializeRequest` schema (validates `protocolVersion`, `clientInfo`, `capabilities`):
   ```python
   class ClientInfo(BaseModel):
       name: str
       version: str

   class InitializeRequest(BaseModel):
       protocolVersion: str
       clientInfo: ClientInfo
       capabilities: dict = {}
   ```

2. Define `InitializeResult` response:
   ```python
   class InitializeResult(BaseModel):
       protocolVersion: str = "2024-11-05"
       serverInfo: ServerInfo
       capabilities: ServerCapabilities
   ```
   where `ServerCapabilities` declares: `tools: {"listChanged": True}`

3. Register handler with FastMCP:
   ```python
   @mcp.initialize_handler
   async def handle_initialize(request: InitializeRequest) -> InitializeResult:
       ...
   ```

4. Validate `protocolVersion` against the list of supported versions (`["2024-11-05"]`); return protocol error for unsupported versions

5. Log the `clientInfo.name` and `clientInfo.version` at `INFO` level for connection audit

## Acceptance Criteria

- [x] Sending an `initialize` message with a supported `protocolVersion` returns a valid `InitializeResult`
- [x] `serverInfo.name` is `"ContextIQ MCP Gateway"` and `serverInfo.version` matches `settings.version`
- [x] Sending an unsupported `protocolVersion` returns a structured MCP error (code `-32600`)
- [x] `clientInfo` with missing `name` or `version` fields returns MCP parse error (code `-32700`)
- [x] Unit tests cover: valid init, unsupported version, malformed request, missing clientInfo fields

## Dependencies

- TASK-US001-01 (FastMCP server bootstrapped)

## Definition of Done

- [x] Handler registered and responding in local dev environment
- [x] Unit test coverage ≥ 90% for `handlers/initialize.py`
- [x] `mypy --strict` passes on `handlers/` module
- [ ] Integration test: Cursor AI dev extension can complete `initialize` handshake with local server
