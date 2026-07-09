# TASK-US006-01 — Define Full Pipeline Topology with Edges and Conditional Routing

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US006-01 |
| User Story | US-006 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Replace the skeleton graph from TASK-US005-01 with the production pipeline topology: sequential edges between all five nodes, conditional edges for the clarification branch and compression-skip optimisation, and a terminal error node for failed states. This is the authoritative pipeline definition that all sub-agent epics (EP-003 through EP-006) plug into.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`

**File locations:**
- `src/agents/graph.py` — full `build_graph()` replacement
- `src/agents/routing.py` — conditional edge predicate functions
- `tests/agents/test_pipeline_topology.py`

**Full pipeline topology:**

```
                          [intent_agent]
                               │
              ┌────────────────┴────────────────┐
        confidence < 0.6                  confidence ≥ 0.6
              │                                  │
     [clarification_response]           [retrieval_agent]
              │                                  │
             END                        [governance_agent]
                                                 │
                                    ┌────────────┴────────────┐
                               tokens ≤ budget           tokens > budget
                                    │                         │
                               [routing_agent]      [compression_agent]
                                    │                         │
                                   END                 [routing_agent]
                                                             │
                                                            END
```

**Graph construction:**
```python
def build_graph(checkpointer, publisher) -> CompiledGraph:
    builder = StateGraph(AgentState)

    # Register nodes (implementations provided by EP-003–EP-006)
    builder.add_node("intent_agent",           wrap(intent_node, "intent_agent", publisher))
    builder.add_node("retrieval_agent",        wrap(retrieval_node, "retrieval_agent", publisher))
    builder.add_node("governance_agent",       wrap(governance_node, "governance_agent", publisher))
    builder.add_node("compression_agent",      wrap(compression_node, "compression_agent", publisher))
    builder.add_node("routing_agent",          wrap(routing_node, "routing_agent", publisher))
    builder.add_node("clarification_response", clarification_node)
    builder.add_node("pipeline_failed",        failed_terminal_node)

    # Entry point
    builder.set_entry_point("intent_agent")

    # Intent → conditional branch
    builder.add_conditional_edges(
        "intent_agent",
        route_after_intent,
        {
            "retrieval":      "retrieval_agent",
            "clarification":  "clarification_response",
            "failed":         "pipeline_failed",
        },
    )

    # Retrieval → Governance (always)
    builder.add_edge("retrieval_agent", "governance_agent")

    # Governance → conditional compression branch
    builder.add_conditional_edges(
        "governance_agent",
        route_after_governance,
        {
            "compress": "compression_agent",
            "skip":     "routing_agent",
            "failed":   "pipeline_failed",
        },
    )

    # Compression → Routing (always, after compression)
    builder.add_edge("compression_agent", "routing_agent")

    # Terminal nodes
    builder.add_edge("routing_agent",          END)
    builder.add_edge("clarification_response", END)
    builder.add_edge("pipeline_failed",        END)

    return builder.compile(checkpointer=checkpointer)
```

**Conditional edge predicates (`routing.py`):**
```python
def route_after_intent(state: AgentState) -> str:
    if state.get("status") == ExecutionStatus.FAILED:
        return "failed"
    if (state.get("intent_confidence") or 1.0) < 0.6:
        return "clarification"
    return "retrieval"

def route_after_governance(state: AgentState) -> str:
    if state.get("status") == ExecutionStatus.FAILED:
        return "failed"
    plan = state.get("execution_plan") or {}
    budget = plan.get("token_budget_total", 8000)
    ranked_tokens = sum(c.get("token_count", 0) for c in (state.get("ranked_context") or []))
    return "compress" if ranked_tokens > budget else "skip"
```

**`clarification_node`:** Sets `final_response = {"type": "clarification", "message": <question>}` and `status = complete`.

**`pipeline_failed` terminal node:** Sets `status = failed`; `error` already set by failing node wrapper (TASK-US006-04).

## Acceptance Criteria

- [ ] Graph compiles with all 7 nodes registered and no dangling edges
- [ ] `route_after_intent` returns `"retrieval"` when `intent_confidence = 0.8`
- [ ] `route_after_intent` returns `"clarification"` when `intent_confidence = 0.4`
- [ ] `route_after_governance` returns `"skip"` when `ranked_tokens ≤ token_budget`
- [ ] `route_after_governance` returns `"compress"` when `ranked_tokens > token_budget`
- [ ] Any node setting `status = failed` routes to `pipeline_failed` terminal
- [ ] Unit tests cover all 5 routing predicate branches with boundary values

## Dependencies

- TASK-US005-01 (`AgentState` TypedDict, node stubs)
- TASK-US005-03 (checkpointer parameter)
- TASK-US005-04 (publisher parameter for `wrap()`)

## Definition of Done

- [ ] `build_graph()` is the single source of truth for pipeline topology — no topology logic in node files
- [ ] Unit tests assert correct `next_node` for each conditional branch
- [ ] `mypy --strict` passes on `graph.py` and `routing.py`
- [ ] Pipeline diagram in `docs/architecture/pipeline-topology.md` updated to match this implementation
