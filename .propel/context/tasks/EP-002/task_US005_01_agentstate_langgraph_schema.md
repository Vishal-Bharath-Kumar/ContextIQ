# TASK-US005-01 — Define AgentState TypedDict and Compile LangGraph StateGraph Skeleton

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US005-01 |
| User Story | US-005 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Define the canonical `AgentState` TypedDict that flows through every node of the LangGraph `StateGraph`, and compile the skeleton graph with placeholder nodes for each pipeline stage. This is the structural foundation for the entire multi-agent pipeline (EP-002 through EP-010).

## Implementation Details

**Technology:** Python 3.11+, `langgraph`, `typing_extensions`

**File locations:**
- `src/agents/state.py` — `AgentState` TypedDict and `StatusEnum`
- `src/agents/graph.py` — `StateGraph` definition, node registration, and compiled graph
- `src/agents/nodes/__init__.py` — stub node modules (one file per pipeline stage)
- `tests/agents/test_state_schema.py`

**`AgentState` TypedDict:**
```python
from typing import TypedDict, Optional, Literal
from datetime import datetime

class ExecutionStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    FAILED   = "failed"

class AgentState(TypedDict):
    # ── Identity (set at init, immutable) ──────────────────────────────
    request_id:        str            # UUID v4
    user_id:           str            # JWT sub claim
    username:          str
    roles:             list[str]
    tool_name:         str            # MCP tool that triggered this request
    prompt:            str            # raw user prompt
    timestamp:         str            # ISO-8601 UTC

    # ── Pipeline status ────────────────────────────────────────────────
    status:            ExecutionStatus
    current_node:      str            # name of the node currently executing
    error:             Optional[str]

    # ── Intent detection output (EP-003) ──────────────────────────────
    intent_type:       Optional[str]
    intent_confidence: Optional[float]
    execution_plan:    Optional[dict]  # token budgets, source list, ranking strategy

    # ── Retrieval output (EP-004) ──────────────────────────────────────
    raw_context:       Optional[list[dict]]   # pre-compression chunks
    ranked_context:    Optional[list[dict]]   # post-ranking chunks

    # ── Compression output (EP-005) ────────────────────────────────────
    compressed_context: Optional[list[dict]]
    tokens_before_compression: Optional[int]
    tokens_after_compression:  Optional[int]

    # ── Governance output (EP-010) ─────────────────────────────────────
    governance_decisions: Optional[list[dict]]  # allow/deny per chunk
    redacted_chunks:      Optional[list[str]]   # chunk IDs that were redacted

    # ── Model routing output (EP-006) ──────────────────────────────────
    selected_model:    Optional[str]
    model_routing_score: Optional[float]
    final_response:    Optional[dict]
```

**Graph skeleton (`graph.py`):**
```python
from langgraph.graph import StateGraph, END

def build_graph() -> CompiledGraph:
    builder = StateGraph(AgentState)

    builder.add_node("intent_agent",      intent_node)
    builder.add_node("retrieval_agent",   retrieval_node)
    builder.add_node("governance_agent",  governance_node)
    builder.add_node("compression_agent", compression_node)
    builder.add_node("routing_agent",     routing_node)

    builder.set_entry_point("intent_agent")
    builder.add_edge("intent_agent",      "retrieval_agent")
    builder.add_edge("retrieval_agent",   "governance_agent")
    builder.add_edge("governance_agent",  "compression_agent")
    builder.add_edge("compression_agent", "routing_agent")
    builder.add_edge("routing_agent",     END)

    return builder.compile(checkpointer=get_redis_checkpointer())  # wired in TASK-US005-03

# Stub nodes — return state unchanged until EP-003–EP-006 implement them
async def intent_node(state: AgentState) -> AgentState:
    return {**state, "current_node": "intent_agent", "status": "running"}
```

**Conditional edge for clarification (US-011):**
```python
builder.add_conditional_edges(
    "intent_agent",
    lambda s: "clarification" if s.get("intent_confidence", 1.0) < 0.6 else "retrieval_agent",
    {"clarification": END, "retrieval_agent": "retrieval_agent"},
)
```

**Graph compiled as application singleton:** `build_graph()` is called once during FastAPI lifespan. The compiled graph is injected via `Depends` into request handlers.

## Acceptance Criteria

- [ ] `AgentState` TypedDict contains all 23 fields listed above with correct types
- [ ] `StateGraph` compiles without error: `builder.compile()` succeeds with all 5 nodes registered
- [ ] Calling `graph.invoke(initial_state)` with stub nodes returns a mutated state without exception
- [ ] `AgentState` is forward-compatible: adding new optional fields does not break existing graph invocations
- [ ] Unit tests assert: all required fields present in `AgentState.__annotations__`, graph compiles, stub invocation completes

## Dependencies

- `langgraph>=0.2.0` added to `pyproject.toml`
- TASK-US005-03 (Redis checkpointer wired into `build_graph()`)

## Definition of Done

- [ ] `state.py` and `graph.py` merged; all 5 stub nodes importable without errors
- [ ] Unit coverage ≥ 85% for `agents/state.py` and `agents/graph.py`
- [ ] `mypy --strict` passes on `state.py` (all TypedDict fields typed)
- [ ] `ruff` clean; no unused imports in stub node files
