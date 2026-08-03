# TASK-US011-02 — MCP `clarification_needed` Response Schema

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US011-02 |
| User Story | US-011 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend / API |
| Priority | P1 |
| Points | 1 |
| Status | Draft |

## Description

Define the `ClarificationNeededResponse` Pydantic model and update the MCP Gateway `tools/call` handler to serialize a clarification response as a valid MCP `tools/call` result — not an error. The MCP client must receive a structured `TextContent` payload that the IDE or AI assistant can display to the user and route their reply back through the `clarification_reply` tool (TASK-US011-04).

## Implementation Details

**Technology:** Python 3.11+, FastMCP, Pydantic v2

**File locations:**
- `src/gateway/schemas/clarification_response.py` — `ClarificationNeededResponse` model
- `src/gateway/handlers/tools_call.py` — result serialisation branch (extends TASK-US003-01)
- `tests/gateway/test_clarification_response_schema.py`

**`ClarificationNeededResponse` model:**

```python
# src/gateway/schemas/clarification_response.py
from typing import Literal
from pydantic import BaseModel

class ClarificationNeededResponse(BaseModel):
    type:              Literal["clarification_needed"] = "clarification_needed"
    question:          str          # ≤ 50-word question from clarification_node
    original_prompt:   str          # the ambiguous prompt, echoed for client context
    session_id:        str          # thread_id — client must include in clarification_reply call
    clarification_round: int = 0    # current round number; client may display for UX
```

**Serialisation in `tools/call` handler:**

The Agent Worker returns an `AgentWorkerResponse` whose `output.data` contains the serialised `AgentState` final result. When the pipeline exits via the `clarification_response` node the handler checks the response type and wraps it:

```python
# src/gateway/handlers/tools_call.py  (extend existing handle_tool_call — TASK-US003-01)
from src.gateway.schemas.clarification_response import ClarificationNeededResponse

async def handle_tool_call(name: str, arguments: dict) -> list[TextContent]:
    # ... existing dispatch logic ...
    output = await agent_worker_client.execute(dispatch)

    if output.data.get("type") == "clarification_needed":
        clar = ClarificationNeededResponse.model_validate(output.data)
        return [TextContent(type="text", text=clar.model_dump_json())]

    # Happy-path serialisation unchanged
    return [TextContent(type="text", text=json.dumps(output.data))]
```

**Agent Worker response construction (extend `src/agents/nodes/clarification_node.py`):**

`clarification_node` must write `final_response` in the shape expected by the Gateway:

```python
# src/agents/nodes/clarification_node.py  (extends TASK-US011-01)
return {
    "requires_clarification":  True,
    "clarification_question":  question.question,
    "status":                  ExecutionStatus.COMPLETE,
    "final_response": {
        "type":               "clarification_needed",
        "question":           question.question,
        "original_prompt":    state["prompt"],
        "session_id":         state["request_id"],
        "clarification_round": state.get("clarification_round", 0),
    },
}
```

**Why not an MCP error:** MCP errors (`McpError`) terminate the tool invocation with an error code visible to the calling model. A `clarification_needed` response is a legitimate, successful tool result that the IDE or LLM orchestrator must handle as a conversation turn — the user's reply is the next action, not a retry.

## Acceptance Criteria

- [ ] `ClarificationNeededResponse` validates successfully with all five fields
- [ ] `tools/call` handler returns HTTP 200 with `TextContent` payload when pipeline exits via clarification path
- [ ] `TextContent.text` is valid JSON deserialising to `ClarificationNeededResponse` shape
- [ ] `type` field value is exactly `"clarification_needed"` — not `"clarification"` or `"error"`
- [ ] `session_id` in the response matches the `request_id` used to initiate the pipeline run
- [ ] No `McpError` is raised for a clarification exit — error codes are reserved for actual failures

## Dependencies

- TASK-US003-01 (`tools/call` handler — `handle_tool_call()` extended here)
- TASK-US011-01 (`clarification_node()` — sets `final_response` and `clarification_question`)
- TASK-US011-04 (`clarification_reply` tool — `session_id` passed back in the reply call)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test asserts `TextContent` payload shape for a mocked clarification pipeline exit
- [ ] JSON schema for `ClarificationNeededResponse` is documented in `docs/api/mcp-response-schemas.md`
- [ ] `mypy --strict` passes; no `ruff` lint errors
