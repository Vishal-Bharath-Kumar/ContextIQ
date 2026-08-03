# TASK-US011-04 — Clarification Re-Submission: Merged Prompt and Second-Pass Intent Classification

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US011-04 |
| User Story | US-011 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend / API |
| Priority | P1 |
| Points | 3 |
| Status | Draft |

## Description

Implement the `clarification_reply` MCP tool that accepts the user's answer to the clarification question, merges it with the original prompt into a single enriched prompt, and re-enters the LangGraph pipeline from the `intent_agent` node with `clarification_round = 1`. The second-pass classifier receives the merged prompt and produces a plan at higher confidence.

## Implementation Details

**Technology:** Python 3.11+, FastMCP, LangGraph, Pydantic v2

**File locations:**
- `src/gateway/tools/clarification_reply.py` — `clarification_reply` MCP tool registration
- `src/gateway/schemas/clarification_reply.py` — `ClarificationReplyInput` input schema
- `src/agents/planning/prompt_merger.py` — `merge_prompt()` function
- `src/agents/worker/execute.py` — re-entry path with incremented round counter
- `tests/gateway/test_clarification_reply_tool.py`

**`ClarificationReplyInput` schema:**

```python
# src/gateway/schemas/clarification_reply.py
from pydantic import BaseModel, Field

class ClarificationReplyInput(BaseModel):
    session_id:        str = Field(description="session_id from ClarificationNeededResponse")
    clarification:     str = Field(
        description="User's answer to the clarification question.",
        min_length=1,
        max_length=2_000,
    )
```

**`clarification_reply` MCP tool registration:**

```python
# src/gateway/tools/clarification_reply.py
@mcp.tool()
async def clarification_reply(session_id: str, clarification: str) -> list[TextContent]:
    """Submit a clarification answer and resume the pipeline with the enriched prompt."""
    args = ClarificationReplyInput(session_id=session_id, clarification=clarification)

    # Restore previous AgentState from LangGraph checkpointer using session_id as thread_id
    prior_state = await graph.aget_state(config={"configurable": {"thread_id": args.session_id}})
    if prior_state is None:
        raise McpError(INVALID_PARAMS, f"Session '{args.session_id}' not found or expired")

    values = prior_state.values
    merged = merge_prompt(
        original_prompt       = values["prompt"],
        clarification_question = values["clarification_question"],
        user_clarification    = args.clarification,
    )

    # Build re-entry state patch
    resume_state: dict = {
        "prompt":               merged,
        "clarification_round":  1,
        "requires_clarification": False,
        "status":               ExecutionStatus.PENDING,
        # Reset intent fields so the second-pass classification runs fresh
        "intent_type":          None,
        "intent_confidence":    None,
        "intent_source_list":   None,
        "execution_plan":       None,
    }

    result = await graph.ainvoke(
        resume_state,
        config={"configurable": {"thread_id": args.session_id}},
    )

    return [TextContent(type="text", text=json.dumps(result.get("final_response", {})))]
```

**`merge_prompt()` function:**

```python
# src/agents/planning/prompt_merger.py

MERGE_TEMPLATE = """\
[Original request]
{original_prompt}

[Clarification asked]
{clarification_question}

[User clarification]
{user_clarification}
"""

def merge_prompt(
    original_prompt:        str,
    clarification_question: str,
    user_clarification:     str,
) -> str:
    """Produce a single enriched prompt that gives the classifier full context."""
    return MERGE_TEMPLATE.format(
        original_prompt        = original_prompt.strip(),
        clarification_question = clarification_question.strip(),
        user_clarification     = user_clarification.strip(),
    )
```

**LangGraph re-entry via `ainvoke` on an existing thread:**
- LangGraph resumes from the `intent_agent` entry point because `status = PENDING` and the graph's entry point is `intent_agent` regardless of prior checkpointed state
- The `thread_id` is reused from the original session so the execution trace remains contiguous (EP-011 sees one trace with two intent spans)
- `clarification_round = 1` is injected in the state patch so `route_after_intent` enforces the cap (TASK-US011-03)

**Session TTL guard:**
- LangGraph checkpoints expire per Redis TTL set in TASK-US005-03; if the session has expired, `aget_state` returns `None` and the tool raises `McpError(INVALID_PARAMS, ...)`
- No new TTL configuration is needed; the existing checkpoint TTL applies

## Acceptance Criteria

- [ ] `clarification_reply` is registered as a discoverable MCP tool with a valid `inputSchema`
- [ ] Calling `clarification_reply` with a valid `session_id` resumes the pipeline from `intent_agent`
- [ ] `merge_prompt()` output contains all three sections: original, question, user answer
- [ ] `AgentState.clarification_round` is `1` during the second-pass `intent_node` execution
- [ ] Second-pass `intent_node` receives the merged prompt, not the original prompt alone
- [ ] Calling `clarification_reply` with an expired or unknown `session_id` returns `McpError(INVALID_PARAMS, ...)`
- [ ] `clarification_reply` tool is visible in the `tools/list` response after registration

## Dependencies

- TASK-US011-01 (`clarification_question` in `AgentState` — needed for `merge_prompt()`)
- TASK-US011-02 (`session_id` in `ClarificationNeededResponse` — passed back in this call)
- TASK-US011-03 (`clarification_round = 1` triggers the round-cap guard in routing)
- TASK-US005-03 (Redis checkpointer — `aget_state()` reads the persisted prior state)
- TASK-US002-01 (`tools/list` handler — `clarification_reply` appears in the registry)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `clarification_reply` input schema is validated via JSON Schema before pipeline re-entry
- [ ] `merge_prompt()` unit tested with: normal case, whitespace trimming, max-length clarification
- [ ] Integration test: full round-trip from initial call → clarification → reply → second-pass result
- [ ] `mypy --strict` passes; no `ruff` lint errors
