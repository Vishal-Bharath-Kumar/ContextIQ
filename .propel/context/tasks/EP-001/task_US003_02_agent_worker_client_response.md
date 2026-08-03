# TASK-US003-02 — Agent Worker HTTP Client and Output Schema Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US003-02 |
| User Story | US-003 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Implement the async HTTP client that calls the Agent Worker's `/v1/execute` endpoint and validates the response against the tool's declared output schema before returning it to the handler. Includes timeout enforcement to uphold the p95 < 3 s SLA.

## Implementation Details

**Technology:** Python 3.11+, `httpx.AsyncClient`, Pydantic v2, `jsonschema`

**File locations:**
- `src/gateway/clients/agent_worker_client.py` — `AgentWorkerClient` class
- `src/gateway/schemas/call_types.py` — `ToolCallDispatch`, `AgentWorkerResponse`, `ToolCallOutput`
- `tests/gateway/test_agent_worker_client.py` — tests with `pytest-httpx`

**`AgentWorkerClient` design:**

```python
class AgentWorkerClient:
    BASE_URL: str  # from settings: AGENT_WORKER_BASE_URL
    TIMEOUT_SECONDS: float = 5.0   # hard timeout > 3 s SLA + buffer

    async def execute(self, dispatch: ToolCallDispatch) -> ToolCallOutput:
        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{self.BASE_URL}/v1/execute",
                json=dispatch.model_dump(),
                headers={
                    "X-Request-ID": dispatch.request_id,
                    "X-Trace-ID": format(dispatch.trace_id, "032x"),
                    "Authorization": f"Bearer {await self._get_service_token()}",
                },
            )
            resp.raise_for_status()
            return AgentWorkerResponse.model_validate(resp.json()).output
```

**Response schema:**

```python
class ToolCallOutput(BaseModel):
    data: dict | list | str          # tool-specific payload
    output_schema_version: str = "1.0"

class AgentWorkerResponse(BaseModel):
    request_id: str
    status: Literal["success", "error"]
    output: ToolCallOutput | None = None
    error: ToolCallError | None = None
    duration_ms: int
```

**Output schema validation** (after receiving Agent Worker response):
```python
output_schema = tool_def.output_schema   # stored in tool_registry alongside inputSchema
if output_schema:
    try:
        jsonschema.validate(instance=output.data, schema=output_schema)
    except jsonschema.ValidationError as e:
        # Log schema mismatch as WARNING — do not block the response
        logger.warning("Output schema mismatch for tool %s: %s", tool_name, e.message)
        span.set_attribute("contextiq.output_schema_valid", False)
```
Output schema violations are logged and metriced but do not fail the call (best-effort validation — the tool author is responsible for schema accuracy).

**Timeout handling:**
```python
except httpx.TimeoutException:
    raise McpError(INTERNAL_ERROR, "Agent pipeline timed out", {"timeout_ms": int(TIMEOUT_SECONDS * 1000)})
except httpx.HTTPStatusError as e:
    raise McpError(INTERNAL_ERROR, f"Agent Worker returned {e.response.status_code}")
```

**Service-to-service auth:** Gateway obtains a short-lived service JWT from Vault (`pki/issue/contextiq-gateway`) and attaches it as Bearer token. Token cached for 4 minutes (< 5-minute expiry).

## Acceptance Criteria

- [ ] Successful Agent Worker response is deserialized into `ToolCallOutput` and returned to handler
- [ ] HTTP timeout after 5 s raises `McpError(INTERNAL_ERROR)` with `timeout_ms` detail
- [ ] Agent Worker HTTP 5xx raises `McpError(INTERNAL_ERROR)` with status code in detail
- [ ] Output with `output_schema` violation logs a WARNING but still returns the response (no hard failure)
- [ ] Service token is fetched from Vault once and cached for 4 minutes (verified via mock call count)
- [ ] `X-Request-ID` and `X-Trace-ID` headers are present on every outbound request (verified via `pytest-httpx` request capture)

## Dependencies

- TASK-US003-01 (dispatches to this client)
- EP-TECH-002 Vault (US-047) for service token
- US-005 (Agent Worker `/v1/execute` endpoint definition — defines `AgentWorkerResponse` contract)

## Definition of Done

- [ ] `pytest-httpx` added to dev dependencies for request interception in tests
- [ ] Unit coverage ≥ 85% for `clients/agent_worker_client.py`
- [ ] `AGENT_WORKER_BASE_URL` and `AGENT_WORKER_TIMEOUT_SECONDS` documented in `.env.example`
- [ ] Integration test: gateway dispatches to a running Agent Worker stub and receives valid `ToolCallOutput`
- [ ] Output schema mismatch metric `contextiq_output_schema_violations_total{tool_name}` confirmed in Prometheus
