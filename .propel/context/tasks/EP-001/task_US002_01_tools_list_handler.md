# TASK-US002-01 — Implement `tools/list` MCP Handler

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US002-01 |
| User Story | US-002 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Register the FastMCP `tools/list` message handler that returns the current set of active tool definitions to an AI assistant. The handler must satisfy the MCP protocol schema and respond within the 200 ms SLA for up to 50 registered tools.

## Implementation Details

**Technology:** Python 3.11+, FastMCP, Pydantic v2

**File locations:**
- `src/gateway/handlers/tools_list.py` — `tools/list` handler
- `src/gateway/schemas/tool_types.py` — `ToolDefinition`, `InputSchema`, `ToolListResult` Pydantic models
- `tests/gateway/test_tools_list_handler.py` — unit and integration tests

**Key implementation steps:**

1. Define tool schema models conforming to MCP spec:
   ```python
   class InputSchema(BaseModel):
       type: Literal["object"] = "object"
       properties: dict[str, dict] = {}
       required: list[str] = []

   class ToolDefinition(BaseModel):
       name: str
       description: str
       inputSchema: InputSchema

   class ToolListResult(BaseModel):
       tools: list[ToolDefinition]
   ```

2. Register handler with FastMCP:
   ```python
   @mcp.list_tools()
   async def handle_tools_list() -> list[ToolDefinition]:
       return await tool_registry_service.get_active_tools()
   ```

3. `tool_registry_service.get_active_tools()` must:
   - First attempt cache hit (Redis) — see TASK-US002-03
   - On cache miss: query PostgreSQL for `status = 'active'` tools
   - Return `ToolDefinition` objects sorted by `name` ASC

4. Benchmark: measure handler latency with 50 tool definitions in a local test to confirm < 200 ms; include `pytest-benchmark` fixture in test file.

## Acceptance Criteria

- [ ] `tools/list` response is a valid `ToolListResult` with `tools` array
- [ ] Each tool entry contains exactly: `name` (string), `description` (string), `inputSchema` (JSON Schema object)
- [ ] Handler returns in < 200 ms when serving from cache with 50 tools (measured via `pytest-benchmark`)
- [ ] Empty `tools` array is returned when no tools are registered (not an error)
- [ ] Handler is idempotent — repeated calls with no registry changes return identical results

## Dependencies

- TASK-US001-01 (FastMCP server bootstrapped)
- TASK-US002-02 (tool registry service providing data)
- TASK-US002-03 (Redis cache layer)

## Definition of Done

- [ ] Handler registered and responding in local dev environment
- [ ] Unit test coverage ≥ 90% for `handlers/tools_list.py`
- [ ] Benchmark test: p95 latency < 200 ms for 50 tools asserted in CI
- [ ] `mypy --strict` passes; no `ruff` errors
