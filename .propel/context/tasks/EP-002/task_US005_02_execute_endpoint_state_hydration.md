# TASK-US005-02 — Implement `POST /v1/execute` Entrypoint and Initial State Hydration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US005-02 |
| User Story | US-005 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement the Agent Worker's `POST /v1/execute` HTTP endpoint that receives a dispatch payload from the MCP Gateway, constructs the initial `AgentState`, attaches a UUID v4 `request_id`, and invokes the compiled LangGraph graph. This is the bridge between the MCP gateway (EP-001) and the agent pipeline (EP-002 onward).

## Implementation Details

**Technology:** Python 3.11+, FastAPI, `langgraph`, `uuid`

**File locations:**
- `src/agent_worker/main.py` — FastAPI app for Agent Worker service
- `src/agent_worker/routers/execute.py` — `POST /v1/execute` router
- `src/agent_worker/schemas/execute_types.py` — `ExecuteRequest`, `ExecuteResponse`
- `tests/agent_worker/test_execute_endpoint.py`

**Request / response schemas:**
```python
class ExecuteRequest(BaseModel):
    request_id: str           # UUID from gateway — used as LangGraph thread_id
    user_id: str
    username: str
    roles: list[str]
    tool_name: str
    arguments: dict           # raw MCP tool arguments
    trace_id: str             # W3C traceparent propagated from gateway

class ExecuteResponse(BaseModel):
    request_id: str
    status: Literal["success", "error"]
    output: dict | None = None
    error: ToolCallError | None = None
    duration_ms: int
```

**Initial state hydration:**
```python
@router.post("/v1/execute", response_model=ExecuteResponse)
async def execute(
    req: ExecuteRequest,
    graph: CompiledGraph = Depends(get_graph),
):
    initial_state: AgentState = {
        "request_id":  req.request_id,
        "user_id":     req.user_id,
        "username":    req.username,
        "roles":       req.roles,
        "tool_name":   req.tool_name,
        "prompt":      req.arguments.get("prompt", ""),
        "timestamp":   datetime.utcnow().isoformat() + "Z",
        "status":      ExecutionStatus.PENDING,
        "current_node": "",
        "error":       None,
        # All downstream fields initialised to None — set by pipeline nodes
        "intent_type": None, "intent_confidence": None, "execution_plan": None,
        "raw_context": None, "ranked_context": None,
        "compressed_context": None,
        "tokens_before_compression": None, "tokens_after_compression": None,
        "governance_decisions": None, "redacted_chunks": None,
        "selected_model": None, "model_routing_score": None,
        "final_response": None,
    }

    config = {"configurable": {"thread_id": req.request_id}}
    t_start = time.monotonic()

    try:
        final_state = await graph.ainvoke(initial_state, config=config)
        duration_ms = int((time.monotonic() - t_start) * 1000)
        return ExecuteResponse(
            request_id=req.request_id,
            status="success",
            output=final_state.get("final_response"),
            duration_ms=duration_ms,
        )
    except Exception as e:
        logger.exception("Pipeline failure for request %s", req.request_id)
        return ExecuteResponse(
            request_id=req.request_id,
            status="error",
            error=ToolCallError(code=-32603, message=str(e)),
            duration_ms=int((time.monotonic() - t_start) * 1000),
        )
```

**`thread_id` = `request_id`:** LangGraph uses `thread_id` as the checkpoint key. Passing `request_id` ensures each tool call has its own isolated checkpoint namespace in Redis.

**Service authentication:** Agent Worker validates the `Authorization: Bearer <token>` header using the same JWKS client as the gateway (service-to-service JWT from Vault PKI — see TASK-US003-02).

**`GET /healthz`:** Returns `{"status": "ok", "graph_compiled": true}` — confirms graph is compiled and ready.

## Acceptance Criteria

- [ ] `POST /v1/execute` with a valid `ExecuteRequest` returns HTTP 200 `ExecuteResponse` with `status: "success"`
- [ ] `initial_state.request_id` equals `req.request_id` from the gateway dispatch payload
- [ ] `initial_state.timestamp` is a valid ISO-8601 UTC string set at request receipt time
- [ ] `initial_state.status` is `"pending"` at the moment of graph invocation
- [ ] An unhandled exception from the graph returns HTTP 200 with `status: "error"` (not HTTP 500 — gateway must always receive a structured response)
- [ ] `GET /healthz` returns `{"status": "ok", "graph_compiled": true}` within 100 ms
- [ ] Unit tests cover: valid dispatch, missing `prompt` in arguments, graph exception handling

## Dependencies

- TASK-US005-01 (`AgentState` schema and compiled graph)
- TASK-US003-01 (gateway sends `ExecuteRequest` to this endpoint)
- TASK-US005-03 (Redis checkpointer — graph won't compile without it)

## Definition of Done

- [ ] Agent Worker `POST /v1/execute` endpoint deployed as a separate Kubernetes `Deployment` in `contextiq-agents` namespace
- [ ] Unit coverage ≥ 90% for `routers/execute.py`
- [ ] Integration test: gateway calls Agent Worker stub and receives `ExecuteResponse` with matching `request_id`
- [ ] Helm chart for `contextiq-agent-worker` created with readiness probe on `/healthz`
