# Pipeline Topology

## Overview

The ContextIQ multi-agent pipeline is implemented as a LangGraph `StateGraph`.
`build_graph()` in `src/agents/graph.py` is the single source of truth for all
topology decisions — edges, conditional routing, and terminal states.

## Node Inventory

| Node | File | Description |
|---|---|---|
| `intent_agent` | `src/agents/nodes/intent.py` | Detects intent type and confidence score (EP-003) |
| `retrieval_agent` | `src/agents/nodes/retrieval.py` | Fetches ranked context from knowledge sources (EP-004) |
| `governance_agent` | `src/agents/nodes/governance.py` | Applies RBAC / policy redaction to retrieved chunks (EP-010) |
| `compression_agent` | `src/agents/nodes/compression.py` | Summarises context when token count exceeds budget (EP-005) |
| `routing_agent` | `src/agents/nodes/routing.py` | Selects target model and produces final response (EP-006) |
| `clarification_response` | `src/agents/graph.py` | Terminal: returns a clarification question to the user |
| `pipeline_failed` | `src/agents/graph.py` | Terminal: marks the pipeline as FAILED |

## Topology Diagram

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

Any node that sets status = FAILED → [pipeline_failed] → END
```

## Conditional Edge Predicates

Predicate functions live in `src/agents/routing.py`.

### `route_after_intent(state)`

| Condition | Next node key |
|---|---|
| `state.status == FAILED` | `"failed"` |
| `intent_confidence < 0.6` | `"clarification"` |
| `intent_confidence ≥ 0.6` (or `None`) | `"retrieval"` |

### `route_after_governance(state)`

| Condition | Next node key |
|---|---|
| `state.status == FAILED` | `"failed"` |
| `sum(ranked_context[].token_count) > token_budget_total` | `"compress"` |
| `sum(ranked_context[].token_count) ≤ token_budget_total` | `"skip"` |

> The default `token_budget_total` when `execution_plan` is absent is **8 000 tokens**.

## Error Handling

Any node (or its wrapper) may set `state.status = FAILED` and populate
`state.error`.  The next conditional edge check routes the execution to the
`pipeline_failed` terminal node, which canonicalises `status = FAILED` before
ending the graph.

## Related Files

- `src/agents/graph.py` — `build_graph()`, `clarification_node`, `failed_terminal_node`
- `src/agents/routing.py` — `route_after_intent`, `route_after_governance`
- `src/agents/state.py` — `AgentState`, `ExecutionStatus`
- `tests/agents/test_pipeline_topology.py` — unit tests for all routing branches
