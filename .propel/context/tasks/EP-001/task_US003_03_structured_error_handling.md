# TASK-US003-03 — Structured Error Handling for Tool Call Failures

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US003-03 |
| User Story | US-003 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement a unified error-handling strategy for the `tools/call` pipeline so that every failure mode (validation error, agent timeout, pipeline exception, schema mismatch) returns a structured MCP error payload without terminating the session or causing an unhandled exception to propagate.

## Implementation Details

**Technology:** Python 3.11+, FastMCP, Python `logging`

**File locations:**
- `src/gateway/errors/tool_errors.py` — error code constants and `build_tool_error()` factory
- `src/gateway/middleware/error_handler.py` — ASGI-level unhandled exception catch-all
- `src/gateway/handlers/tools_call.py` — per-error `try/except` blocks (augments TASK-US003-01)
- `tests/gateway/test_tool_error_handling.py`

**Error taxonomy and MCP error codes:**

| Failure | MCP Error Code | `code` value |
|---|---|---|
| Tool not found | `INVALID_PARAMS` | `-32602` |
| Input schema violation | `INVALID_PARAMS` | `-32602` |
| Agent Worker timeout | `INTERNAL_ERROR` | `-32603` |
| Agent Worker 5xx | `INTERNAL_ERROR` | `-32603` |
| Circuit breaker open | Custom (`-32001`) | `-32001` |
| Agent pipeline logic error | `INTERNAL_ERROR` | `-32603` |
| Unexpected exception | `INTERNAL_ERROR` | `-32603` |

**MCP error response structure** (returned as `isError: true` content block per MCP spec):
```python
def build_tool_error(code: int, message: str, detail: dict | None = None) -> list[TextContent]:
    payload = {"error": {"code": code, "message": message}}
    if detail:
        payload["error"]["data"] = detail
    return [TextContent(type="text", text=json.dumps(payload))]
```

**Handler error-wrapping pattern:**
```python
@mcp.call_tool()
async def handle_tool_call(name: str, arguments: dict) -> list[TextContent]:
    try:
        ...  # dispatch and return
    except McpError:
        raise                                        # re-raise typed MCP errors as-is
    except httpx.TimeoutException:
        logger.error("timeout", extra={"tool": name, "request_id": dispatch.request_id})
        return build_tool_error(-32603, "Agent pipeline timed out", {"tool": name})
    except CircuitBreakerError:
        return build_tool_error(-32001, "Service temporarily unavailable", {"retry_after_seconds": 60})
    except Exception as e:
        logger.exception("Unexpected tool call failure for tool %s", name)
        return build_tool_error(-32603, "Internal error", {"tool": name})
```

**Session persistence guarantee:** errors are returned as a valid MCP `CallToolResult` with `isError=True` — the session is never dropped, the MCP connection remains open, and subsequent calls from the same session proceed normally.

**ASGI catch-all middleware** (`error_handler.py`): catches any exception that escapes the handler (e.g., from FastMCP internals) and returns a 500 JSON response — preventing connection resets.

**Error metrics:**
```python
tool_call_errors_total = Counter(
    "contextiq_tool_call_errors_total",
    "Tool call errors by type",
    ["tool_name", "error_type"]   # error_type: timeout | validation | pipeline | unknown
)
```

## Acceptance Criteria

- [ ] Tool not found returns `isError: true` with code `-32602` and does not drop the MCP session
- [ ] Agent Worker timeout returns `isError: true` with code `-32603` and `timeout_ms` detail
- [ ] Circuit-breaker open state returns `isError: true` with code `-32001` and `retry_after_seconds`
- [ ] An unhandled exception inside the handler returns `isError: true` (no raw 500 to the MCP client)
- [ ] The MCP session (SSE/WebSocket connection) remains open after any error response — verified by sending a second tool call in the same session
- [ ] `contextiq_tool_call_errors_total{error_type="timeout"}` increments on every timeout
- [ ] Unit tests cover every failure mode in the taxonomy table above

## Dependencies

- TASK-US003-01 (handler structure to augment with try/except)
- TASK-US003-02 (HTTP client exceptions — `TimeoutException`, `HTTPStatusError`)
- TASK-US001-04 (circuit-breaker raises `CircuitBreakerError`)

## Definition of Done

- [ ] All 7 failure modes unit-tested; each asserts `isError: true` in the response content
- [ ] Session persistence test: error followed by successful call in same MCP session passes in integration test
- [ ] Error Prometheus counter confirmed in Grafana "Tool Call Error Rate" panel
- [ ] No `bare except` or swallowed exceptions — `ruff` rule `BLE001` enabled and passing
