# TASK-US003-01 — Implement `tools/call` Handler with Input Validation and Pipeline Dispatch

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US003-01 |
| User Story | US-003 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Register the FastMCP `tools/call` message handler that validates inbound tool arguments against the registered `inputSchema`, constructs a typed execution request, and dispatches it to the Agent Worker service. This is the primary entry point for AI assistant tool invocations.

## Implementation Details

**Technology:** Python 3.11+, FastMCP, Pydantic v2, `httpx` (async HTTP client)

**File locations:**
- `src/gateway/handlers/tools_call.py` — `tools/call` handler
- `src/gateway/schemas/call_types.py` — `ToolCallRequest`, `ToolCallDispatch`, `ToolCallResponse` models
- `src/gateway/clients/agent_worker_client.py` — async HTTP client for Agent Worker
- `tests/gateway/test_tools_call_handler.py`

**Key implementation steps:**

1. Register the `tools/call` handler:
   ```python
   @mcp.call_tool()
   async def handle_tool_call(name: str, arguments: dict) -> list[TextContent]:
       ...
   ```

2. Validate tool existence — look up `name` in the tool registry (via cache-first `get_active_tools()`); return structured MCP error if not found:
   ```python
   tool_def = await tool_registry_service.get_by_name(name)
   if tool_def is None:
       raise McpError(INVALID_PARAMS, f"Tool '{name}' not found or inactive")
   ```

3. Validate `arguments` against `tool_def.inputSchema` using `jsonschema.validate`:
   ```python
   try:
       jsonschema.validate(instance=arguments, schema=tool_def.input_schema)
   except jsonschema.ValidationError as e:
       raise McpError(INVALID_PARAMS, f"Invalid arguments: {e.message}")
   ```

4. Construct the dispatch payload and add request context:
   ```python
   dispatch = ToolCallDispatch(
       request_id=str(uuid4()),
       user_id=request_context.user_id,       # injected from JWT middleware
       tool_name=name,
       arguments=arguments,
       trace_id=trace.get_current_span().get_span_context().trace_id,
   )
   ```

5. Dispatch to Agent Worker via `AgentWorkerClient.execute(dispatch)` and await result (see TASK-US003-02 for client implementation).

6. Serialize result as `[TextContent(type="text", text=json.dumps(result.output))]`.

**Agent Worker internal endpoint:**
```
POST http://contextiq-agent-worker.contextiq-agents.svc.cluster.local/v1/execute
Content-Type: application/json
X-Request-ID: {request_id}
X-Trace-ID: {trace_id}
```

## Acceptance Criteria

- [ ] `tools/call` with a valid tool name and correct arguments dispatches to the Agent Worker and returns a result
- [ ] `tools/call` with an unknown tool name returns MCP error code `INVALID_PARAMS` (`-32602`)
- [ ] `tools/call` with arguments that fail JSON Schema validation returns `INVALID_PARAMS` with a descriptive message
- [ ] `dispatch.request_id` is a unique UUID v4 for every invocation
- [ ] `dispatch.trace_id` matches the OTel trace ID of the current span context
- [ ] Unit tests cover: valid call, unknown tool, schema validation failure, missing required argument

## Dependencies

- TASK-US001-01 (FastMCP server), TASK-US001-04 (circuit-breaker wraps Agent Worker call)
- TASK-US002-02 (tool registry — `get_by_name`)
- TASK-US003-02 (Agent Worker client)
- US-005 (Agent Worker `POST /v1/execute` endpoint)

## Definition of Done

- [ ] Handler registered; dispatches successfully to a local Agent Worker stub in integration test
- [ ] Unit coverage ≥ 90% for `handlers/tools_call.py`
- [ ] `jsonschema` added to `pyproject.toml` with version pin
- [ ] `mypy --strict` passes; `ruff` clean
