# TASK-US008-03 — Propagate `degraded_sources` Through Pipeline to MCP Response

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US008-03 |
| User Story | US-008 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Ensure that `degraded_sources` set by the retrieval node (US-007 / TASK-US007-03) is preserved through every downstream pipeline node and ultimately surfaced in the `ToolCallOutput` returned to the MCP gateway, so the AI assistant receives a `degraded_sources` field in its `tools/call` response alongside the partial context.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2

**File locations:**
- `src/agents/state.py` — `degraded_sources` field confirmed in `AgentState` TypedDict
- `src/agents/nodes/contracts.py` — `degraded_sources` added to governance, compression, and routing allowed output sets
- `src/agent_worker/routers/execute.py` — final response includes `degraded_sources` (extends TASK-US005-02)
- `src/gateway/schemas/call_types.py` — `ToolCallOutput` extended with `degraded_sources`
- `tests/agents/test_degraded_sources_propagation.py`

**State field type (confirmed in `AgentState`):**
```python
class DegradedSourceInfo(TypedDict):
    source_id:  str
    error_type: str
    message:    str

# In AgentState TypedDict:
degraded_sources: list[DegradedSourceInfo] | None
```

**Node contract updates** — downstream nodes must not clear `degraded_sources`:
```python
# contracts.py — add to existing sets (nodes that DON'T write degraded_sources
# but must NOT accidentally overwrite it via a full-state return)
NODE_OUTPUT_CONTRACTS: dict[str, set[str]] = {
    "governance_agent":  {..., "degraded_sources"},   # may append governance-denied sources
    "compression_agent": {...},                        # read-only — does NOT touch degraded_sources
    "routing_agent":     {...},                        # read-only — does NOT touch degraded_sources
}
```

Governance agent may add further entries (sources denied by OPA policy) to `degraded_sources`, so it is in its allowed set. Compression and routing nodes are read-only with respect to this field.

**Final response construction in `POST /v1/execute` (TASK-US005-02):**
```python
final_state = await graph.ainvoke(initial_state, config=config)

degraded = final_state.get("degraded_sources") or []
output_payload = {
    **(final_state.get("final_response") or {}),
    "degraded_sources": degraded,    # always present; empty list if no failures
}

return ExecuteResponse(
    request_id=req.request_id,
    status="success",
    output=output_payload,
    duration_ms=elapsed_ms,
)
```

**`ToolCallOutput` update in gateway (`call_types.py`):**
```python
class ToolCallOutput(BaseModel):
    data: dict | list | str
    output_schema_version: str = "1.0"
    degraded_sources: list[DegradedSourceSummary] = []

class DegradedSourceSummary(BaseModel):
    source_id:  str
    error_type: str   # ConnectorTimeoutError | ConnectorCircuitOpenError | <exception class>
    message:    str
```

**MCP response to AI assistant** — the `tools/call` result JSON includes:
```json
{
  "context": [...],
  "degraded_sources": [
    {
      "source_id": "jira:myproject",
      "error_type": "ConnectorTimeoutError",
      "message": "Connector 'jira:myproject' timed out after 5.0s"
    }
  ]
}
```
The AI assistant (Cursor, Copilot, Claude Code) can optionally surface this to the developer as a footnote or warning.

**Empty-context safety:** If `degraded_sources` is non-empty and `context` is empty (all connectors failed), the response is still HTTP 200 with an empty context array and a populated `degraded_sources` — never an error status.

## Acceptance Criteria

- [ ] `degraded_sources` set by the retrieval node is present in the final `AgentState` after pipeline completion
- [ ] Governance, compression, and routing nodes do not clear or overwrite `degraded_sources`
- [ ] `ExecuteResponse.output` always contains a `degraded_sources` key (empty list when no failures)
- [ ] `ToolCallOutput.degraded_sources` is serialised in the MCP `tools/call` response JSON
- [ ] All-connectors-failed scenario returns HTTP 200 with empty `context` and non-empty `degraded_sources`
- [ ] Unit test: pipeline with 1 timed-out connector → final `ToolCallOutput.degraded_sources` has 1 entry with correct `source_id`

## Dependencies

- TASK-US007-03 (`degraded_sources` first written in `ContextAggregator`)
- TASK-US006-02 (`NODE_OUTPUT_CONTRACTS` updated — governance allowed to write `degraded_sources`)
- TASK-US003-02 (`ToolCallOutput` schema extended)

## Definition of Done

- [ ] `DegradedSourceSummary` model added to `call_types.py` and `execute_types.py` — no dict literals
- [ ] Integration test: end-to-end from gateway `tools/call` → agent pipeline → response — confirms `degraded_sources` present in JSON
- [ ] `mypy --strict` passes across all modified schema files
- [ ] API contract documented in OpenAPI: `degraded_sources` field described in `ToolCallOutput` schema
