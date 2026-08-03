# TASK-US006-04 — Pipeline Failure Handling: Failed Node → Structured Error State

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US006-04 |
| User Story | US-006 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement the failure-handling contract that catches any unhandled exception inside a pipeline node, transitions `AgentState.status` to `failed`, populates `AgentState.error` with a structured error payload, and routes to the `pipeline_failed` terminal node — without crashing the LangGraph runtime or returning an unstructured 500 to the MCP gateway.

## Implementation Details

**Technology:** Python 3.11+, `langgraph`

**File locations:**
- `src/agents/nodes/base.py` — `with_error_handling()` wrapper (innermost wrapper in the chain)
- `src/agents/nodes/pipeline_failed.py` — `pipeline_failed` terminal node implementation
- `src/agents/routing.py` — `route_after_intent` and `route_after_governance` check `status == failed`
- `tests/agents/test_pipeline_failure.py`

**`with_error_handling` wrapper (innermost — wraps the raw node function):**
```python
def with_error_handling(node_fn: Callable, node_name: str) -> Callable:
    @functools.wraps(node_fn)
    async def wrapper(state: AgentState) -> dict:
        try:
            return await node_fn(state)
        except Exception as e:
            # Return partial state update that marks the pipeline as failed
            return {
                "status":       ExecutionStatus.FAILED,
                "current_node": node_name,
                "error": json.dumps({
                    "failed_node": node_name,
                    "error_type":  type(e).__name__,
                    "message":     str(e),
                    "timestamp":   utcnow_iso(),
                }),
            }
    return wrapper
```

The node does **not** re-raise — it returns a partial state update. LangGraph merges this into the current `AgentState`, and the conditional edges in TASK-US006-01 detect `status == failed` and route to `pipeline_failed`.

**Updated wrapper composition order (innermost → outermost):**
```
raw node function
  → with_error_handling    (catches, returns failed state)
  → node_contract          (validates output fields in DEBUG)
  → with_node_logging      (logs entry/exit, creates OTel span)
  → with_state_events      (publishes Kafka state transition)
```

**`pipeline_failed` terminal node:**
```python
async def failed_terminal_node(state: AgentState) -> dict:
    # State already has status=failed and error set by the failing node wrapper.
    # This node is a no-op terminal — its sole purpose is to be a named END point
    # so the graph has an explicit failure path visible in topology diagrams.
    return {
        "status": ExecutionStatus.FAILED,
        "current_node": "pipeline_failed",
    }
```

**Gateway receives structured failure:**
Back in `POST /v1/execute` (TASK-US005-02), the caller checks `final_state["status"]`:
```python
if final_state["status"] == ExecutionStatus.FAILED:
    error_detail = json.loads(final_state.get("error") or "{}")
    return ExecuteResponse(
        request_id=req.request_id,
        status="error",
        error=ToolCallError(
            code=-32603,
            message=error_detail.get("message", "Pipeline failed"),
            data=error_detail,
        ),
        duration_ms=elapsed_ms,
    )
```

**Mid-pipeline failures:** Nodes after the failure are never executed. Example: if `retrieval_agent` fails:
- `retrieval_agent` wrapper returns `{status: failed, error: {...}}`
- LangGraph checkpoints this state
- `route_after_governance` sees `status == failed` → routes to `pipeline_failed` → END
- Nodes `compression_agent` and `routing_agent` never execute

**Error field structure:**
```json
{
  "failed_node":  "retrieval_agent",
  "error_type":   "ConnectionRefusedError",
  "message":      "Connection refused to Qdrant",
  "timestamp":    "2026-07-09T10:23:45Z"
}
```

## Acceptance Criteria

- [ ] An exception in `intent_agent` results in `final_state["status"] == "failed"` with `"failed_node": "intent_agent"` in the error JSON
- [ ] An exception in `retrieval_agent` does not execute `compression_agent` or `routing_agent` (verified by node call-count mock)
- [ ] `pipeline_failed` terminal node is always the last node executed on any failure path
- [ ] `POST /v1/execute` returns HTTP 200 with `status: "error"` (not HTTP 500) for any pipeline failure
- [ ] `AgentState.error` contains valid JSON with `failed_node`, `error_type`, `message`, and `timestamp`
- [ ] Kafka `running → failed` event is published for the failing node (via `with_state_events` in wrapper chain)
- [ ] Unit tests: each of the 5 nodes failing produces correct `error` JSON and skips subsequent nodes

## Dependencies

- TASK-US006-01 (conditional edges route `status==failed` to `pipeline_failed`)
- TASK-US006-02 (`with_error_handling` added as innermost wrapper in `wrap()`)
- TASK-US005-04 (Kafka `failed` event published by `with_state_events` wrapper)

## Definition of Done

- [ ] Failure handling unit-tested for all 5 pipeline nodes in isolation
- [ ] Integration test: force each node to raise an exception; verify `POST /v1/execute` always returns structured JSON with `status: "error"`
- [ ] `pipeline_failed` terminal node visible in pipeline topology diagram
- [ ] `contextiq_pipeline_node_duration_seconds{status="failed"}` histogram increments on every failure (from TASK-US006-03)
